#pragma once

// BogPilot confidence ball: the comma four "confidence ball" on BogPilot's Qt driving screen.
//
// Ported from openpilot selfdrive/ui/mici/onroad/confidence_ball.py (commaai/openpilot a742df6,
// MIT License, Copyright (c) 2018, Comma.ai, Inc.). Same math and colors: the model's own
// disengage predictions give confidence = (1 - max(brakeDisengageProbs)) * (1 - max(steerOverrideProbs)),
// smoothed by a first-order filter (rc 0.5 s, starts at -0.5). Engaged: the ball rides high and green
// above 50%, orange above 20%, red below. Driver override: white to grey. Disengaged: the target is
// -0.5, so a dark ball slides out of the bottom of the screen.
//
// Layout for the comma 3X (2160x1080): a 60 px strip on the right edge of the onroad window that
// covers the 30 px status border and the 30 px camera margin, so the ball never overlaps the
// Experimental button, pedal icons, compass, bottom-right icons or the Developer HUD panel
// (all of those end 30 px inside the camera view).
//
// Display only. On/off is a file, /data/params_bogpilot/ConfidenceBall ("0"/"false"/"off" hides it,
// anything else or no file shows it), because the prebuilt params_pyx.so cannot store new Params keys.

#include <algorithm>
#include <utility>

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QLinearGradient>
#include <QPainter>
#include <QWidget>

#include "common/util.h"
#include "selfdrive/ui/ui.h"

namespace bogpilot_confidence {

inline QString togglePath() {
  return QStringLiteral("/data/params_bogpilot/ConfidenceBall");
}

// Same read rules as BogPilot's other /data/params_bogpilot switches; default on.
inline bool fileEnabled(const QString &path = togglePath()) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly)) {
    return true;
  }
  const QByteArray text = file.read(64).trimmed();
  return !(text == "0" || text == "false" || text == "off");
}

inline void setFileEnabled(bool on, const QString &path = togglePath()) {
  QDir().mkpath(QFileInfo(path).absolutePath());
  QFile file(path);
  if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
    file.write(on ? "1" : "0");
  }
}

// Any active openpilot status (engaged, Always On Lateral, traffic mode, ...) counts as engaged.
inline bool engagedStatus(UIStatus status) {
  return status != STATUS_DISENGAGED && status != STATUS_OVERRIDE;
}

template <typename List>
inline float maxOrOne(const List &probs) {
  if (probs.size() == 0) {
    return 1.0f;
  }
  float m = probs[0];
  for (float p : probs) {
    m = std::max(m, p);
  }
  return m;
}

// Python: (1 - max(brakeDisengageProbs or [1])) * (1 - max(steerOverrideProbs or [1]))
inline float modelConfidence(const cereal::ModelDataV2::Reader &model) {
  const auto dp = model.getMeta().getDisengagePredictions();
  return (1.0f - maxOrOne(dp.getBrakeDisengageProbs())) * (1.0f - maxOrOne(dp.getSteerOverrideProbs()));
}

// Top and bottom gradient colors, exactly as on the comma four.
inline std::pair<QColor, QColor> ballColors(UIStatus status, float x) {
  if (engagedStatus(status)) {
    if (x > 0.5f) return {QColor(0, 255, 204), QColor(0, 255, 38)};
    if (x > 0.2f) return {QColor(255, 200, 0), QColor(255, 115, 0)};
    return {QColor(255, 0, 21), QColor(255, 0, 89)};
  }
  if (status == STATUS_OVERRIDE) {
    return {QColor(255, 255, 255), QColor(82, 82, 82)};
  }
  return {QColor(50, 50, 50), QColor(13, 13, 13)};
}

// Vertical gradient clipped to a circle.
inline void paintBall(QPainter &p, const QPointF &center, float radius, const QColor &top, const QColor &bottom) {
  QLinearGradient gradient(center.x(), center.y() - radius, center.x(), center.y() + radius);
  gradient.setColorAt(0.0, top);
  gradient.setColorAt(1.0, bottom);
  p.save();
  p.setRenderHint(QPainter::Antialiasing);
  p.setPen(Qt::NoPen);
  p.setBrush(gradient);
  p.drawEllipse(center, radius, radius);
  p.restore();
}

// Ball center height inside a track of the given height: (1 - x) * (h - 2r - 2m) + r + m.
inline float ballCenterY(float x, float track_height, float radius, float margin) {
  return (1.0f - x) * (track_height - 2.0f * radius - 2.0f * margin) + radius + margin;
}

}  // namespace bogpilot_confidence

class ConfidenceBall : public QWidget {
public:
  static constexpr int STRIP_WIDTH = 2 * UI_BORDER_SIZE;  // status border + camera margin
  static constexpr float RADIUS = 27.0f;                  // 54 px ball (comma four: 24 on a much smaller screen)
  static constexpr float MARGIN = 3.0f;

  explicit ConfidenceBall(QWidget *parent) : QWidget(parent) {
    setAttribute(Qt::WA_TransparentForMouseEvents, true);
    setAttribute(Qt::WA_NoSystemBackground, true);
    setVisible(false);
  }

  // Right edge of the parent, full height.
  void placeIn(const QRect &parent_rect) {
    setGeometry(parent_rect.right() + 1 - STRIP_WIDTH, parent_rect.top(), STRIP_WIDTH, parent_rect.height());
  }

  // Called every UI tick (20 Hz). camera_at_right_edge is false when the map covers the right side.
  void updateState(const UIState &s, bool camera_at_right_edge) {
    if (check_frame-- <= 0) {
      enabled = bogpilot_confidence::fileEnabled();
      check_frame = UI_FREQ * 2;  // re-read the file every 2 s
    }

    status = s.status;
    if (status == STATUS_DISENGAGED) {
      filter.update(-0.5f);
    } else {
      filter.update(bogpilot_confidence::modelConfidence((*s.sm)["modelV2"].getModelV2()));
    }

    const bool visible_now = enabled && s.scene.started && camera_at_right_edge;
    if (visible_now != isVisible()) {
      setVisible(visible_now);
      if (visible_now) raise();
    }
    if (!visible_now) {
      return;
    }

    const int y = (int)bogpilot_confidence::ballCenterY(filter.x(), height(), RADIUS, MARGIN);
    const auto colors = bogpilot_confidence::ballColors(status, filter.x());
    if (y != drawn_y || colors.first != drawn_top) {
      update();
    }
  }

  float confidence() { return filter.x(); }

protected:
  void paintEvent(QPaintEvent *event) override {
    QPainter p(this);
    const auto colors = bogpilot_confidence::ballColors(status, filter.x());
    drawn_y = (int)bogpilot_confidence::ballCenterY(filter.x(), height(), RADIUS, MARGIN);
    drawn_top = colors.first;
    bogpilot_confidence::paintBall(p, QPointF(width() / 2.0, drawn_y), RADIUS, colors.first, colors.second);
  }

private:
  FirstOrderFilter filter = FirstOrderFilter(-0.5f, 0.5f, 1.0f / UI_FREQ);
  UIStatus status = STATUS_DISENGAGED;
  bool enabled = true;
  int check_frame = 0;
  int drawn_y = -1;
  QColor drawn_top;
};
