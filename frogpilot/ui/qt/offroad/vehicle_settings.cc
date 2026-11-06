#include <QRegularExpression>
#include <QTextStream>

#include "frogpilot/ui/qt/offroad/vehicle_settings.h"
#include "frogpilot/ui/qt/widgets/bogpilot_file_toggle.h"

QStringList getCarNames(const QString &carMake, QMap<QString, QString> &carModels) {
  static QMap<QString, QString> makeMap = {
    {"acura", "honda"},
    {"audi", "volkswagen"},
    {"buick", "gm"},
    {"cadillac", "gm"},
    {"chevrolet", "gm"},
    {"chrysler", "chrysler"},
    {"cupra", "volkswagen"},
    {"dodge", "chrysler"},
    {"ford", "ford"},
    {"genesis", "hyundai"},
    {"gmc", "gm"},
    {"holden", "gm"},
    {"honda", "honda"},
    {"hyundai", "hyundai"},
    {"jeep", "chrysler"},
    {"kia", "hyundai"},
    {"lexus", "toyota"},
    {"lincoln", "ford"},
    {"man", "volkswagen"},
    {"mazda", "mazda"},
    {"nissan", "nissan"},
    {"ram", "chrysler"},
    {"seat", "volkswagen"},
    {"škoda", "volkswagen"},
    {"subaru", "subaru"},
    {"tesla", "tesla"},
    {"toyota", "toyota"},
    {"volkswagen", "volkswagen"}
  };

  QStringList carNameList;

  QFile valuesFile(QString("../car/%1/values.py").arg(makeMap.value(carMake, carMake)));
  if (!valuesFile.open(QIODevice::ReadOnly | QIODevice::Text)) {
    return carNameList;
  }

  QString fileContent = QTextStream(&valuesFile).readAll();
  valuesFile.close();

  fileContent.remove(QRegularExpression("#[^\n]*"));
  fileContent.remove(QRegularExpression("footnotes=\\[[^\\]]*\\],\\s*"));

  static QRegularExpression carNameRegex("CarDocs\\(\\s*\"([^\"]+)\"[^)]*\\)");
  static QRegularExpression platformRegex("((\\w+)\\s*=\\s*\\w+\\s*\\(\\s*\\[([\\s\\S]*?)\\]\\s*,)");
  static QRegularExpression validNameRegex("^[A-Za-z0-9 \u0160.()-]+$");

  QRegularExpressionMatchIterator platformMatches = platformRegex.globalMatch(fileContent);
  while (platformMatches.hasNext()) {
    QRegularExpressionMatch platformMatch = platformMatches.next();
    QString platformName = platformMatch.captured(2);
    QString platformSection = platformMatch.captured(3);

    QRegularExpressionMatchIterator carNameMatches = carNameRegex.globalMatch(platformSection);
    while (carNameMatches.hasNext()) {
      QString carName = carNameMatches.next().captured(1);

      if (carName.contains(validNameRegex) && carName.count(" ") >= 1) {
        QString firstWord = carName.section(" ", 0, 0);

        if (firstWord.compare(carMake, Qt::CaseInsensitive) == 0) {
          carModels[carName] = platformName;
          carNameList.append(carName);
        }
      }
    }
  }

  carNameList.sort();
  return carNameList;
}

FrogPilotVehiclesPanel::FrogPilotVehiclesPanel(FrogPilotSettingsWindow *parent) : FrogPilotListWidget(parent), parent(parent) {
  QJsonObject shownDescriptions = QJsonDocument::fromJson(QString::fromStdString(params.get("ShownToggleDescriptions")).toUtf8()).object();
  QString className = this->metaObject()->className();

  if (!shownDescriptions.value(className).toBool(false)) {
    forceOpenDescriptions = true;
    shownDescriptions.insert(className, true);
    params.put("ShownToggleDescriptions", QJsonDocument(shownDescriptions).toJson(QJsonDocument::Compact).toStdString());
  }

  QStackedLayout *vehiclesLayout = new QStackedLayout();
  addItem(vehiclesLayout);

  FrogPilotListWidget *settingsList = new FrogPilotListWidget(this);

  ScrollView *vehiclesPanel = new ScrollView(settingsList, this);

  vehiclesLayout->addWidget(vehiclesPanel);

  QStringList makes = {
    "Acura", "Audi", "Buick", "Cadillac", "Chevrolet", "Chrysler",
    "CUPRA", "Dodge", "Ford", "Genesis", "GMC", "Holden", "Honda",
    "Hyundai", "Jeep", "Kia", "Lexus", "Lincoln", "MAN", "Mazda",
    "Nissan", "Ram", "SEAT", "Škoda", "Subaru", "Tesla", "Toyota",
    "Volkswagen"
  };

  ButtonControl *selectMakeButton = new ButtonControl(tr("Car Make"), tr("SELECT"));
  QObject::connect(selectMakeButton, &ButtonControl::clicked, [makes, selectMakeButton, this]() {
    QString makeSelection = MultiOptionDialog::getSelection(tr("Choose your car make"), makes, "", this);
    if (!makeSelection.isEmpty()) {
      params.put("CarMake", makeSelection.toStdString());
      selectMakeButton->setValue(makeSelection);
    }
  });
  settingsList->addItem(selectMakeButton);

  ButtonControl *selectModelButton = new ButtonControl(tr("Car Model"), tr("SELECT"));
  QObject::connect(selectModelButton, &ButtonControl::clicked, [selectModelButton, this]() {
    QString modelSelection = MultiOptionDialog::getSelection(tr("Choose your car model"), getCarNames(QString::fromStdString(params.get("CarMake")).toLower(), carModels), "", this);
    if (!modelSelection.isEmpty()) {
      params.put("CarModel", carModels.value(modelSelection).toStdString());
      params.put("CarModelName", modelSelection.toStdString());
      selectModelButton->setValue(modelSelection);
      this->parent->updateVariables();
      updateToggles();
    }
  });
  settingsList->addItem(selectModelButton);

  forceFingerprint = new ParamControl("ForceFingerprint", tr("Disable Automatic Fingerprint Detection"), tr("<b>Force the selected fingerprint</b> and prevent it from ever changing."), "");
  settingsList->addItem(forceFingerprint);

  disableOpenpilotLong = new ParamControl("DisableOpenpilotLongitudinal", tr("Disable openpilot Longitudinal Control"), tr("<b>Disable openpilot longitudinal</b> and use the car's stock ACC instead."), "");
  QObject::connect(disableOpenpilotLong, &ToggleControl::toggleFlipped, [parent, this](bool state) {
    if (state) {
      if (FrogPilotConfirmationDialog::yesorno(tr("Are you sure you want to completely disable openpilot longitudinal control?"), this)) {
        if (started) {
          if (FrogPilotConfirmationDialog::toggleReboot(this)) {
            Hardware::reboot();
          }
        }
      } else {
        params.putBool("DisableOpenpilotLongitudinal", false);
        disableOpenpilotLong->refresh();
      }
    }

    parent->updateVariables();
    updateToggles();
  });
  settingsList->addItem(disableOpenpilotLong);

  FrogPilotListWidget *gmList = new FrogPilotListWidget(this);
  FrogPilotListWidget *hkgList = new FrogPilotListWidget(this);
  FrogPilotListWidget *hondaList = new FrogPilotListWidget(this);
  FrogPilotListWidget *subaruList = new FrogPilotListWidget(this);
  FrogPilotListWidget *teslaList = new FrogPilotListWidget(this);
  FrogPilotListWidget *teslaPreapList = new FrogPilotListWidget(this);
  FrogPilotListWidget *toyotaList = new FrogPilotListWidget(this);
  FrogPilotListWidget *vehicleInfoList = new FrogPilotListWidget(this);

  ScrollView *gmPanel = new ScrollView(gmList, this);
  ScrollView *hkgPanel = new ScrollView(hkgList, this);
  ScrollView *hondaPanel = new ScrollView(hondaList, this);
  ScrollView *subaruPanel = new ScrollView(subaruList, this);
  ScrollView *teslaPanel = new ScrollView(teslaList, this);
  ScrollView *teslaPreapPanel = new ScrollView(teslaPreapList, this);
  ScrollView *toyotaPanel = new ScrollView(toyotaList, this);
  ScrollView *vehicleInfoPanel = new ScrollView(vehicleInfoList, this);

  vehiclesLayout->addWidget(gmPanel);
  vehiclesLayout->addWidget(hkgPanel);
  vehiclesLayout->addWidget(hondaPanel);
  vehiclesLayout->addWidget(subaruPanel);
  vehiclesLayout->addWidget(teslaPanel);
  vehiclesLayout->addWidget(teslaPreapPanel);
  vehiclesLayout->addWidget(toyotaPanel);
  vehiclesLayout->addWidget(vehicleInfoPanel);

  std::vector<std::tuple<QString, QString, QString, QString>> vehicleToggles {
    {"GMToggles", tr("General Motors Settings"), tr("<b>BogPilot features for General Motors vehicles.</b>"), ""},
    {"ExperimentalGMTune", tr("FrogsGoMoo's Experimental Tune"), tr("<b>Experimental GM tune by FrogsGoMoo</b> that attempts to smoothen stopping and takeoff control. Use at your own risk!"), ""},
    {"LongPitch", tr("Smooth Pedal Response on Hills"), tr("<b>Smoothen acceleration and braking</b> when driving downhill/uphill."), ""},
    {"VoltSNG", tr("Stop-and-Go Hack"), tr("<b>Force stop-and-go</b> on the 2017 Chevy Volt."), ""},

    {"HKGToggles", tr("Hyundai/Kia/Genesis Settings"), tr("<b>BogPilot features for Genesis, Hyundai, and Kia vehicles.</b>"), ""},
    {"NewLongAPI", tr("comma's New Longitudinal API"), tr("<b>comma's new gas and brake control system</b> that improves acceleration and braking but may cause issues on some Genesis/Hyundai/Kia vehicles."), ""},
    {"TacoTuneHacks", tr("\"Taco Bell Run\" Torque Hack"), tr("<b>The steering torque hack from comma's 2022 \"Taco Bell Run\".</b> Designed to increase steering torque at low speeds for left and right turns."), ""},

    {"HondaToggles", tr("Acura/Honda Settings"), tr("<b>BogPilot features for Acura and Honda vehicles.</b>"), ""},
    {"HondaAltTune", tr("Gentle Following"), tr("<b>Reduces jerky acceleration and braking when following a lead vehicle.</b> Ideal for stop-and-go traffic."), ""},
    {"HondaMaxBrake", tr("Increased Braking Force"), tr("<b>Increases the maximum braking force for improved stopping performance.</b>"), ""},
    {"HondaLowSpeedPedal", tr("Responsive Pedal at Low Speeds"), tr("<b>Improves acceleration from a standstill for a more responsive throttle feel in city driving.</b>"), ""},

    {"SubaruToggles", tr("Subaru Settings"), tr("<b>BogPilot features for Subaru vehicles.</b>"), ""},
    {"SubaruSNG", tr("Stop and Go"), tr("Stop and go for supported Subaru vehicles."), ""},

    {"TeslaAP1Toggles", tr("Tesla AP1 Settings"), tr("<b>BogPilot features for Tesla Model S and X with Autopilot 1.</b>"), ""},
    {"EnableICIntegration", tr("Dash Cluster Integration"), QString("<b>%1</b><br><br>%2").arg(tr("Show openpilot on the Tesla dash cluster while engaged: the cluster set speed (including curve and speed limit targets), the Autosteer icon, hands-on reminders, and the path line.")).arg(tr("Turn off to leave the dash cluster completely stock. openpilot then sends no cluster messages. Driving is the same either way. Takes effect right away.")), ""},
    {"RegenComfortBrake", tr("Earlier, Gentler Regen Stops"), QString("<b>%1</b><br><br>%2").arg(tr("Start slowing for a car ahead sooner and more gently, sized to what regen alone can do (about 1.0 m/s²).")).arg(tr("Hard braking for cut-ins, collision warnings, and emergencies is unchanged, and so is the stopped distance. Turn off for stock openpilot following. Takes effect right away.")), ""},

    // Pre-AP only — copy mirrored from selfdrive/car/tesla/preap/menu_copy.py
    {"TeslaPreAPToggles", tr("Tesla Pre-AP Settings"), tr("<b>BogPilot features for Tesla Model S Pre-AP</b> (no Autopilot ECU): comma pedal longitudinal and optional Bosch radar."), ""},
    {"PedalStatus", tr("Comma Pedal"), tr("<b>Comma Pedal status.</b> Not detected = no pedal reply on the selected CAN bus. Needs calibration = pedal seen; run Calibrate before longitudinal. Ready = detected and calibrated; longitudinal can use it."), ""},
    {"PedalCalibrate", tr("Calibrate Pedal"), tr("<b>Calibrate the comma pedal.</b> Park the car, foot off the pedal, then press Calibrate and follow the prompts: keep foot off for coast, then press the pedal fully once. Required before longitudinal."), ""},
    {"PedalCanBus", tr("Pedal CAN Bus"), tr("<b>Which CAN bus the comma pedal is on.</b> Bus 2 is the usual install. Use bus 0 only if your pedal is wired there. Wrong bus shows Not detected."), ""},
    {"TeslaRadarEnabled", tr("Bosch Radar"), tr("<b>Pre-AP Bosch radar.</b> Off by default. On lets BogPilot wake the radar and use its tracks. Needs a wired Bosch radar. Leave off if you have no radar."), ""},
    {"TeslaRadarBehindNosecone", tr("Radar Behind Nosecone"), tr("<b>Radar mounted behind the nosecone.</b> On if the Bosch unit sits behind the nosecone (common Pre-AP retrofit). Off if it is in the open bumper position."), ""},
    {"TeslaRadarOffset", tr("Radar Lateral Offset"), tr("<b>Sideways radar mount offset.</b> Positive = radar right of centerline, negative = left. Shown in inches; stored in meters. Use 0 in if the radar is centered."), ""},
    {"TeslaRadarIgnoreHwFail", tr("Ignore Radar Hardware Errors"), tr("<b>Ignore Bosch radar hardware-fail bit.</b> Off by default (same as NAP NAPRadarIgnoreHwFail). On lets BogPilot keep using radar tracks when RADC_HWFail is set — useful for a false hardware fail with live tracks. Pre-AP already ignores SGUFail (calibration / VIN / summary lamp) so engage is not blocked by that alone. Takes effect right away; no reboot."), ""},
    {"TeslaRadarReadVin", tr("Read Radar VIN"), tr("<b>Read the Bosch radar donor VIN (F190).</b> Off by default. On lets BogPilot request the VIN from the radar over UDS while offroad / before engage, store it locally, and put it on the GTW VIN helper frames instead of the dummy. Never writes a VIN to the radar. Takes effect right away; no reboot."), ""},
    {"TeslaRadarUpsideDown", tr("Radar Mounted Upside Down"), tr("<b>Radar mounted upside down.</b> Off by default. On inverts lateral distance and lateral velocity from the Bosch tracks so an inverted mount still tracks correctly. Pre-AP only. Takes effect right away; no reboot."), ""},

    {"ToyotaToggles", tr("Toyota/Lexus Settings"), tr("<b>BogPilot features for Lexus and Toyota vehicles.</b>"), ""},
    {"ToyotaDoors", tr("Automatically Lock/Unlock Doors"), tr("<b>Automatically lock/unlock doors</b> when shifting in and out of drive."), ""},
    {"ClusterOffset", tr("Dashboard Speed Offset"), tr("<b>The speed offset openpilot uses to match the speed on the dashboard display.</b>"), ""},
    {"ToyotaDSUBypass", tr("DSU Re-Route Harness"), tr("<b>Enable openpilot longitudinal control using a DSU re-route harness.</b> This harness wires the DSU's ACC messages onto the camera CAN bus so openpilot can send its own longitudinal commands. Only enable this after physically installing the harness on your TSS-P vehicle."), ""},
    {"FrogsGoMoosTweak", tr("FrogsGoMoo's Personal Tweaks"), tr("<b>Personal tweaks by FrogsGoMoo for quicker acceleration and smoother braking.</b>"), ""},
    {"LockDoorsTimer", tr("Lock Doors On Ignition Off After"), tr("<b>Automatically lock the doors on ignition off</b> when no one is detected in the front seats."), ""},
    {"SNGHack", tr("Stop-and-Go Hack"), tr("<b>Force stop-and-go</b> on Lexus/Toyota vehicles without stock stop-and-go functionality."), ""},

    {"VehicleInfo", tr("Vehicle Info"), tr("<b>Information about your vehicle in regards to openpilot support and functionality.</b>"), ""},
    {"HardwareDetected", tr("3rd Party Hardware Detected"), tr("<b>Detected 3rd party hardware.</b>"), ""},
    {"BlindSpotSupport", tr("Blind Spot Support"), tr("<b>Does openpilot use the vehicle's blind spot data?</b>"), ""},
    {"PedalSupport", tr("comma Pedal Support"), tr("<b>Does your vehicle support the \"comma pedal\"?</b>"), ""},
    {"OpenpilotLongitudinal", tr("openpilot Longitudinal Support"), tr("<b>Can openpilot control the vehicle's acceleration and braking?</b>"), ""},
    {"RadarSupport", tr("Radar Support"), tr("<b>Does openpilot use the vehicle's radar data</b> alongside the device's camera for tracking lead vehicles?"), ""},
    {"SDSUSupport", tr("SDSU Support"), tr("<b>Does your vehicle support \"SDSUs\"?</b>"), ""},
    {"SNGSupport", tr("Stop-and-Go Support"), tr("<b>Does your vehicle support stop-and-go driving?</b>"), ""}
  };

  for (const auto &[param, title, desc, icon] : vehicleToggles) {
    AbstractControl *vehicleToggle;

    if (param == "GMToggles") {
      ButtonControl *gmButton = new ButtonControl(title, tr("MANAGE"), desc);
      QObject::connect(gmButton, &ButtonControl::clicked, [vehiclesLayout, gmPanel, this]() {
        openDescriptions(forceOpenDescriptions, toggles);
        vehiclesLayout->setCurrentWidget(gmPanel);
      });
      vehicleToggle = gmButton;

    } else if (param == "HKGToggles") {
      ButtonControl *hkgButton = new ButtonControl(title, tr("MANAGE"), desc);
      QObject::connect(hkgButton, &ButtonControl::clicked, [vehiclesLayout, hkgPanel, this]() {
        openDescriptions(forceOpenDescriptions, toggles);
        vehiclesLayout->setCurrentWidget(hkgPanel);
      });
      vehicleToggle = hkgButton;

    } else if (param == "HondaToggles") {
      ButtonControl *hondaButton = new ButtonControl(title, tr("MANAGE"), desc);
      QObject::connect(hondaButton, &ButtonControl::clicked, [vehiclesLayout, hondaPanel, this]() {
        openDescriptions(forceOpenDescriptions, toggles);
        vehiclesLayout->setCurrentWidget(hondaPanel);
      });
      vehicleToggle = hondaButton;

    } else if (param == "SubaruToggles") {
      ButtonControl *subaruButton = new ButtonControl(title, tr("MANAGE"), desc);
      QObject::connect(subaruButton, &ButtonControl::clicked, [vehiclesLayout, subaruPanel, this]() {
        openDescriptions(forceOpenDescriptions, toggles);
        vehiclesLayout->setCurrentWidget(subaruPanel);
      });
      vehicleToggle = subaruButton;

    } else if (param == "TeslaAP1Toggles") {
      ButtonControl *teslaButton = new ButtonControl(title, tr("MANAGE"), desc);
      QObject::connect(teslaButton, &ButtonControl::clicked, [vehiclesLayout, teslaPanel, this]() {
        openDescriptions(forceOpenDescriptions, toggles);
        vehiclesLayout->setCurrentWidget(teslaPanel);
      });
      vehicleToggle = teslaButton;
    } else if (param == "TeslaPreAPToggles") {
      ButtonControl *teslaPreapButton = new ButtonControl(title, tr("MANAGE"), desc);
      QObject::connect(teslaPreapButton, &ButtonControl::clicked, [vehiclesLayout, teslaPreapPanel, this]() {
        openDescriptions(forceOpenDescriptions, toggles);
        vehiclesLayout->setCurrentWidget(teslaPreapPanel);
      });
      vehicleToggle = teslaPreapButton;
    } else if (param == "PedalStatus") {
      vehicleToggle = new LabelControl(title, tr("Not detected"), desc);
    } else if (param == "PedalCalibrate") {
      ButtonControl *calibBtn = new ButtonControl(title, tr("CALIBRATE"), desc);
      QObject::connect(calibBtn, &ButtonControl::clicked, [this]() {
        if (FrogPilotConfirmationDialog::yesorno(
              tr("Park, foot off the pedal. OK arms calibration: keep foot off until the interceptor is quiet and the car shows no gas, then press the pedal fully once with your foot. A tiny twitch is rejected. Cancel leaves calibration unchanged."),
              this)) {
          bogpilot::writeFileText("PedalCalibMessage", "");
          bogpilot::writeFileToggle("PedalCalibArmed", true);
        }
      });
      vehicleToggle = calibBtn;
    } else if (param == "PedalCanBus") {
      ButtonControl *busBtn = new ButtonControl(title, tr("SELECT"), desc);
      auto refreshBus = [busBtn]() {
        const int bus = bogpilot::readFileInt("PedalCanBus", 2);
        busBtn->setValue(QString::number(bus == 0 ? 0 : 2));
      };
      refreshBus();
      QObject::connect(busBtn, &ButtonControl::clicked, [refreshBus, this]() {
        QString sel = MultiOptionDialog::getSelection(tr("Pedal CAN Bus"), {"2", "0"},
                      QString::number(bogpilot::readFileInt("PedalCanBus", 2) == 0 ? 0 : 2), this);
        if (!sel.isEmpty()) {
          bogpilot::writeFileInt("PedalCanBus", sel.toInt());
          refreshBus();
        }
      });
      vehicleToggle = busBtn;
    } else if (param == "TeslaRadarEnabled") {
      vehicleToggle = new bogpilot::FileToggleControl(param, false, title, desc, icon);
    } else if (param == "TeslaRadarBehindNosecone") {
      vehicleToggle = new bogpilot::FileToggleControl(param, false, title, desc, icon);
    } else if (param == "TeslaRadarIgnoreHwFail") {
      // NAP NAPRadarIgnoreHwFail default OFF. Live in radar_interface; no reboot.
      vehicleToggle = new bogpilot::FileToggleControl(param, false, title, desc, icon);
    } else if (param == "TeslaRadarReadVin") {
      // Opt-in F190 donor VIN read. Default OFF. Live; no reboot.
      vehicleToggle = new bogpilot::FileToggleControl(param, false, title, desc, icon);
    } else if (param == "TeslaRadarUpsideDown") {
      // Invert LatDist / LatSpeed. Default OFF. Live; no reboot.
      vehicleToggle = new bogpilot::FileToggleControl(param, false, title, desc, icon);
    } else if (param == "TeslaRadarOffset") {
      ButtonControl *offBtn = new ButtonControl(title, tr("SELECT"), desc);
      auto refreshOff = [offBtn]() {
        const double m = bogpilot::readFileFloat("TeslaRadarOffset", 0.0);
        const int inches = qRound(m / 0.0254);
        offBtn->setValue(QString("%1 in").arg(inches));
      };
      refreshOff();
      QObject::connect(offBtn, &ButtonControl::clicked, [refreshOff, this]() {
        QStringList opts;
        for (int inch = -12; inch <= 12; ++inch) {
          opts << QString::number(inch);
        }
        const double m = bogpilot::readFileFloat("TeslaRadarOffset", 0.0);
        const int cur = qRound(m / 0.0254);
        QString sel = MultiOptionDialog::getSelection(tr("Radar offset (inches)"), opts, QString::number(cur), this);
        if (!sel.isEmpty()) {
          bogpilot::writeFileFloat("TeslaRadarOffset", sel.toInt() * 0.0254);
          refreshOff();
        }
      });
      vehicleToggle = offBtn;
    } else if (teslaKeys.contains(param)) {
      // File-backed (see bogpilot_file_toggle.h). Absent file = on, the car code's default.
      vehicleToggle = new bogpilot::FileToggleControl(param, true, title, desc, icon);

    } else if (param == "ToyotaToggles") {
      ButtonControl *toyotaButton = new ButtonControl(title, tr("MANAGE"), desc);
      QObject::connect(toyotaButton, &ButtonControl::clicked, [vehiclesLayout, toyotaPanel, this]() {
        openDescriptions(forceOpenDescriptions, toggles);
        vehiclesLayout->setCurrentWidget(toyotaPanel);
      });
      vehicleToggle = toyotaButton;
    } else if (param == "ToyotaDoors") {
      std::vector<QString> lockToggles{"LockDoors", "UnlockDoors"};
      std::vector<QString> lockToggleNames{tr("Lock"), tr("Unlock")};
      vehicleToggle = new FrogPilotButtonToggleControl(param, title, desc, icon, lockToggles, lockToggleNames);
    } else if (param == "LockDoorsTimer") {
      std::map<float, QString> autoLockLabels;
      for (int i = 0; i <= 300; ++i) {
        autoLockLabels[i] = i == 0 ? tr("Never") : QString::number(i) + tr(" seconds");
      }
      vehicleToggle = new FrogPilotParamValueControl(param, title, desc, icon, 0, 300, QString(), autoLockLabels, 5);
    } else if (param == "ClusterOffset") {
      std::vector<QString> clusterOffsetButton{"Reset"};
      FrogPilotParamValueButtonControl *clusterOffsetToggle = new FrogPilotParamValueButtonControl(param, title, desc, icon, 1.000, 1.050, "x", std::map<float, QString>(), 0.001, false, {}, clusterOffsetButton, false, false);
      QObject::connect(clusterOffsetToggle, &FrogPilotParamValueButtonControl::buttonClicked, [clusterOffsetToggle, this]() {
        params.putFloat("ClusterOffset", params_default.getFloat("ClusterOffset"));
        clusterOffsetToggle->refresh();
      });
      vehicleToggle = clusterOffsetToggle;

    } else if (param == "VehicleInfo") {
      ButtonControl *VehicleInfoButton = new ButtonControl(title, tr("VIEW"), desc);
      QObject::connect(VehicleInfoButton, &ButtonControl::clicked, [vehiclesLayout, vehicleInfoPanel, this]() {
        openDescriptions(forceOpenDescriptions, toggles);
        vehiclesLayout->setCurrentWidget(vehicleInfoPanel);
      });
      vehicleToggle = VehicleInfoButton;
    } else if (vehicleInfoKeys.contains(param)) {
      vehicleToggle = new LabelControl(title, "", desc);

    } else {
      vehicleToggle = new ParamControl(param, title, desc, icon);
    }

    toggles[param] = vehicleToggle;

    if (gmKeys.contains(param)) {
      gmList->addItem(vehicleToggle);
    } else if (hkgKeys.contains(param)) {
      hkgList->addItem(vehicleToggle);
    } else if (hondaKeys.contains(param)) {
      hondaList->addItem(vehicleToggle);
    } else if (subaruKeys.contains(param)) {
      subaruList->addItem(vehicleToggle);
    } else if (teslaKeys.contains(param)) {
      teslaList->addItem(vehicleToggle);
    } else if (teslaPreapKeys.contains(param)) {
      teslaPreapList->addItem(vehicleToggle);
    } else if (toyotaKeys.contains(param)) {
      toyotaList->addItem(vehicleToggle);
    } else if (vehicleInfoKeys.contains(param)) {
      vehicleInfoList->addItem(vehicleToggle);
    } else {
      settingsList->addItem(vehicleToggle);

      parentKeys.insert(param);
    }

    // Manage-panel buttons only — not PedalCalibrate / PedalCanBus / offset SELECT.
    static const QSet<QString> noSubPanelKeys = {"PedalCalibrate", "PedalCanBus", "TeslaRadarOffset"};
    if (!noSubPanelKeys.contains(param)) {
      if (ButtonControl *buttonControl = qobject_cast<ButtonControl*>(vehicleToggle)) {
        QObject::connect(buttonControl, &ButtonControl::clicked, this, &FrogPilotVehiclesPanel::openSubPanel);
      }
    }

    QObject::connect(vehicleToggle, &AbstractControl::hideDescriptionEvent, [this]() {
      update();
    });
    QObject::connect(vehicleToggle, &AbstractControl::showDescriptionEvent, [this]() {
      update();
    });
  }

  static_cast<FrogPilotParamValueControl*>(toggles["LockDoorsTimer"])->setWarning("<b>Warning:</b> openpilot can't detect if keys are still inside the car, so ensure you have a spare key to prevent accidental lockouts!");

  QSet<QString> rebootKeys = {"HondaAltTune", "NewLongAPI", "TacoTuneHacks", "ToyotaDSUBypass"};
  for (const QString &key : rebootKeys) {
    QObject::connect(static_cast<ToggleControl*>(toggles[key]), &ToggleControl::toggleFlipped, [key, this](bool state) {
      if (started) {
        if (key == "HondaAltTune" || key == "TacoTuneHacks" && state) {
          if (FrogPilotConfirmationDialog::toggleReboot(this)) {
            Hardware::reboot();
          }
        } else if (key != "TacoTuneHacks") {
          if (FrogPilotConfirmationDialog::toggleReboot(this)) {
            Hardware::reboot();
          }
        }
      }
    });
  }

  openDescriptions(forceOpenDescriptions, toggles);

  QObject::connect(uiState(), &UIState::offroadTransition, [selectMakeButton, selectModelButton, this]() {
    std::thread([selectMakeButton, selectModelButton, this]() {
      selectMakeButton->setValue(QString::fromStdString(params.get("CarMake", true)));
      selectModelButton->setValue(QString::fromStdString(params.get(params.get("CarModelName").empty() ? "CarModel" : "CarModelName")));
    }).detach();
  });

  QObject::connect(parent, &FrogPilotSettingsWindow::closeSubPanel, [vehiclesLayout, vehiclesPanel, this] {
    if (forceOpenDescriptions) {
      openDescriptions(forceOpenDescriptions, toggles);

      disableOpenpilotLong->showDescription();
      forceFingerprint->showDescription();
    }
    vehiclesLayout->setCurrentWidget(vehiclesPanel);
  });
  QObject::connect(uiState(), &UIState::uiUpdate, this, &FrogPilotVehiclesPanel::updateState);
}

void FrogPilotVehiclesPanel::showEvent(QShowEvent *event) {
  if (forceOpenDescriptions) {
    disableOpenpilotLong->showDescription();
    forceFingerprint->showDescription();
  }

  frogpilotToggleLevels = parent->frogpilotToggleLevels;

  QStringList detected;
  if (parent->hasPedal) detected << "comma Pedal";
  if (parent->hasSDSU) detected << "SDSU";
  if (parent->hasZSS) detected << "ZSS";
  static_cast<LabelControl*>(toggles["HardwareDetected"])->setText(detected.isEmpty() ? tr("None") : detected.join(", "));

  static_cast<LabelControl*>(toggles["BlindSpotSupport"])->setText(parent->hasBSM ? tr("Yes") : tr("No"));
  static_cast<LabelControl*>(toggles["OpenpilotLongitudinal"])->setText(parent->hasOpenpilotLongitudinal ? tr("Yes") : tr("No"));
  static_cast<LabelControl*>(toggles["PedalSupport"])->setText(parent->canUsePedal ? tr("Yes") : tr("No"));
  static_cast<LabelControl*>(toggles["RadarSupport"])->setText(parent->hasRadar ? tr("Yes") : tr("No"));
  static_cast<LabelControl*>(toggles["SDSUSupport"])->setText(parent->canUseSDSU ? tr("Yes") : tr("No"));
  static_cast<LabelControl*>(toggles["SNGSupport"])->setText(parent->hasSNG ? tr("Yes") : tr("No"));

  updateToggles();
}

void FrogPilotVehiclesPanel::updateState(const UIState &s) {
  if (!isVisible()) {
    return;
  }

  started = s.scene.started;
}

void FrogPilotVehiclesPanel::updateToggles() {
  for (auto &[key, toggle] : toggles) {
    if (parentKeys.contains(key)) {
      toggle->setVisible(false);
    }
  }

  for (auto &[key, toggle] : toggles) {
    if (parentKeys.contains(key)) {
      continue;
    }

    bool setVisible = parent->tuningLevel >= frogpilotToggleLevels[key].toDouble();

    if (gmKeys.contains(key)) {
      setVisible &= parent->isGM;
    } else if (hkgKeys.contains(key)) {
      setVisible &= parent->isHKG;
    } else if (hondaKeys.contains(key)) {
      setVisible &= parent->isHonda;
    } else if (subaruKeys.contains(key)) {
      setVisible &= parent->isSubaru;
    } else if (teslaKeys.contains(key)) {
      setVisible &= parent->isTeslaAP1;
    } else if (teslaPreapKeys.contains(key)) {
      setVisible &= parent->isTeslaPreAP;
    } else if (toyotaKeys.contains(key)) {
      setVisible &= parent->isToyota;
    } else if (vehicleInfoKeys.contains(key)) {
      setVisible = true;
    }

    if (longitudinalKeys.contains(key)) {
      setVisible &= parent->hasOpenpilotLongitudinal;
    }

    if (key == "HondaAltTune") {
      setVisible &= parent->isHondaNidec;
    }

    else if (key == "HondaLowSpeedPedal") {
      setVisible &= parent->hasPedal;
    }

    else if (key == "HondaMaxBrake") {
      setVisible &= parent->isHondaNidec;
    }

    else if (key == "SNGHack") {
      setVisible &= !parent->hasPedal && !parent->hasSNG;
    }

    else if (key == "SubaruSNG") {
      setVisible &= parent->hasSNG;
    }

    else if (key == "TacoTuneHacks") {
      setVisible &= parent->isHKGCanFd;
    }

    else if (key == "ToyotaDSUBypass") {
      setVisible &= parent->canUseSDSU && !parent->hasSDSU;
    }

    else if (key == "VoltSNG") {
      setVisible &= parent->isVolt && !parent->hasSNG;
    }

    toggle->setVisible(setVisible);

    if (setVisible) {
      if (gmKeys.contains(key)) {
        toggles["GMToggles"]->setVisible(true);
      } else if (hkgKeys.contains(key)) {
        toggles["HKGToggles"]->setVisible(true);
      } else if (hondaKeys.contains(key)) {
        toggles["HondaToggles"]->setVisible(true);
      } else if (subaruKeys.contains(key)) {
        toggles["SubaruToggles"]->setVisible(true);
      } else if (teslaKeys.contains(key)) {
        toggles["TeslaAP1Toggles"]->setVisible(true);
      } else if (teslaPreapKeys.contains(key)) {
        toggles["TeslaPreAPToggles"]->setVisible(true);
      } else if (toyotaKeys.contains(key)) {
        toggles["ToyotaToggles"]->setVisible(true);
      } else if (vehicleInfoKeys.contains(key)) {
        toggles["VehicleInfo"]->setVisible(true);
      }
    }
  }

  // Pre-AP-only copy for DisableOpenpilotLongitudinal; AP1 keeps stock text.
  if (parent->isTeslaPreAP) {
    disableOpenpilotLong->setTitle(tr("Disable Pedal Longitudinal"));
    disableOpenpilotLong->setDescription(tr("<b>Comma Pedal longitudinal (Pre-AP).</b> Leave this off so BogPilot can drive gas through a detected, calibrated comma pedal. Turn it on to disable pedal longitudinal (steering only). Needs a comma pedal on the selected CAN bus."));
  } else {
    disableOpenpilotLong->setTitle(tr("Disable openpilot Longitudinal Control"));
    disableOpenpilotLong->setDescription(tr("<b>Disable openpilot longitudinal</b> and use the car's stock ACC instead."));
  }

  // Refresh Pre-AP pedal status label from file-backed mirrors.
  if (toggles.count("PedalStatus")) {
    QString status = tr("Not detected");
    if (bogpilot::readFileToggle("PedalCalibArmed", false)) {
      status = tr("Calibrating…");
    } else {
      const QString fail = bogpilot::readFileText("PedalCalibMessage");
      if (!fail.isEmpty()) {
        status = tr("Failed: %1").arg(fail);
      } else if (bogpilot::readFileToggle("PedalDetected", false)) {
        const bool done = bogpilot::readFileToggle("PedalCalibDone", false);
        const QString zero = bogpilot::readFileText("PedalCalibZero");
        const QString factor = bogpilot::readFileText("PedalCalibFactor");
        const bool is_default = (zero.isEmpty() || zero == "0.0" || zero == "0") &&
                                (factor.isEmpty() || factor == "1.0" || factor == "1");
        if (done && !is_default) {
          status = tr("Ready");
        } else {
          status = tr("Needs calibration");
        }
      }
    }
    static_cast<LabelControl*>(toggles["PedalStatus"])->setText(status);
  }

  disableOpenpilotLong->setVisible((parent->hasOpenpilotLongitudinal || parent->openpilotLongitudinalControlDisabled) && !parent->hasExperimentalOpenpilotLongitudinal && parent->tuningLevel >= frogpilotToggleLevels["DisableOpenpilotLongitudinal"].toBool());
  forceFingerprint->setVisible(parent->tuningLevel >= frogpilotToggleLevels["ForceFingerprint"].toBool());

  openDescriptions(forceOpenDescriptions, toggles);

  update();
}
