#pragma once

#include <QElapsedTimer>
#include <QPixmap>
#include <QWidget>

#include "frogpilot/ui/qt/onroad/upload_rate.h"

// Offroad idle face, shown when the offroad screen timeout fires.
// Default ON. File toggle /data/params_bogpilot/OffroadScreensaver
// ("0"/"false"/"off" leaves the screen blank; "1"/"true"/"on", a missing file, or anything else
// shows the screensaver). An explicit "0" written by the settings switch keeps it off.
// July's prebuilt params_pyx.so rejects new Params keys, so this is not a Params key.
//
// Default face: BogPilot logo only (no UPLOAD/Mbps/PENDING/"Up to date").
// Upload bounce (Mbps + PENDING, or logo + "Up to date" when caught up) is opt-in via
// /data/params_bogpilot/ShowUploadRate (missing = off). Same sample as the offroad upload card
// (frogpilot/ui/qt/onroad/upload_rate.h / wifi.cc).

namespace bogpilot_screensaver {
constexpr const char TOGGLE_KEY[] = "OffroadScreensaver";
constexpr bool TOGGLE_DEFAULT = true;  // missing/unknown file = on; must match device_settings.cc
}

class OffroadScreensaver : public QWidget {
  Q_OBJECT

public:
  explicit OffroadScreensaver(QWidget *parent = nullptr);

public slots:
  // True when the offroad timeout should switch to this face. The window shows it.
  bool onInteractiveTimeout();
  void dismiss();

signals:
  void dismissed();

protected:
  void showEvent(QShowEvent *event) override;
  void hideEvent(QHideEvent *event) override;
  void resizeEvent(QResizeEvent *event) override;
  void paintEvent(QPaintEvent *event) override;

private:
  bool refreshSample();
  void relayout();
  void tick();
  QRect contentRect() const;

  QTimer *sampleTimer = nullptr;
  QTimer *animTimer = nullptr;
  QElapsedTimer clock;

  QPixmap logo;
  QPixmap logoScaled;
  bogpilot_uprate::Sample sample;
  qint64 ageS = 0;
  bool caughtUp = false;
  bool rateShown = false;
  bool showPending = false;
  bool stale = false;
  int toggleTicks = 0;

  float x = 40.f;
  float y = 40.f;
  float vx = 260.f;
  float vy = 150.f;
  int contentW = 1;
  int contentH = 1;
};
