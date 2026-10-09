#include "frogpilot/ui/qt/onroad/bogpilot_redesign.h"

#include <algorithm>
#include <cmath>

#include <QFile>
#include <QFontMetricsF>
#include <QPainterPath>

bool bogpilotRedesignFileEnabled(const QString &path) {
  QFile f(path);
  if (!f.open(QIODevice::ReadOnly)) return true;
  const QString text = QString::fromUtf8(f.read(16)).trimmed().toLower();
  return !(text == "0" || text == "false" || text == "off");
}

namespace bogpilot {

namespace {

constexpr qreal CAP_RADIUS = 44;
constexpr qreal COL_MAX = 140, COL_SPEED = 370, COL_LIMIT = 612;   // screen 170 / 400 / 642
constexpr qreal DIV_1 = 250, DIV_2 = 490;                          // screen 280 / 520
constexpr qreal BASELINE = SPEED_ROW_TOP + 114;  // shared numeral baseline (screen y 168)
constexpr qreal LABEL_BASELINE = BASELINE + 36;  // screen y 204
constexpr int SIDE_PX = 66, BIG_PX = 100, LABEL_PX = 22;
constexpr int TILE_LABEL_PX = 16;

const QColor SIGN_FILL(244, 244, 242, 238);
const QColor SIGN_EDGE(20, 20, 20);
const QColor SIGN_INK(14, 14, 14);
const QColor SIGN_LABEL(55, 55, 55);

}  // namespace

QFont font(int px, QFont::Weight weight) {
  QFont f("Inter");
  f.setPixelSize(px);
  f.setWeight(weight);
  return f;
}

void paintPanel(QPainter &p, const QRectF &r, qreal radius, const QColor &fill, const QColor &stroke, qreal stroke_w) {
  p.save();
  p.setRenderHint(QPainter::Antialiasing);
  p.setBrush(fill);
  p.setPen(stroke.alpha() > 0 ? QPen(stroke, stroke_w) : QPen(Qt::NoPen));
  p.drawRoundedRect(r, radius, radius);
  p.restore();
}

void drawCentredBaseline(QPainter &p, qreal cx, qreal baseline, const QString &text) {
  const qreal w = QFontMetricsF(p.font()).horizontalAdvance(text);
  p.drawText(QPointF(cx - w / 2, baseline), text);
}

QString spaced(const QString &s) {
  QString out;
  for (int i = 0; i < s.size(); ++i) {
    if (i) out += ' ';
    out += s[i];
  }
  return out;
}

// ---------------- speed row ----------------

SpeedRowGeometry speedRowGeometry(const SpeedRowInputs &in) {
  SpeedRowGeometry g;
  const qreal y0 = SPEED_ROW_TOP, y1 = SPEED_ROW_TOP + SPEED_ROW_HEIGHT;
  qreal x1 = DIV_2 + 14;
  if (in.show_limit) {
    qreal tx0, tx1, ty0, ty1;
    if (in.vienna) {
      const qreal d = 128;
      tx0 = COL_LIMIT - d / 2; tx1 = COL_LIMIT + d / 2;
      ty0 = BASELINE - 92; ty1 = ty0 + d;
    } else {
      const qreal nw = QFontMetricsF(font(SIDE_PX, QFont::Bold)).horizontalAdvance(in.limit);
      const qreal lw = QFontMetricsF(font(TILE_LABEL_PX, QFont::Bold)).horizontalAdvance(in.limit_label);
      const qreal half = std::max(nw, lw) / 2 + 22;
      tx0 = COL_LIMIT - half; tx1 = COL_LIMIT + half;
      ty0 = BASELINE - 92; ty1 = BASELINE + 40;
    }
    g.tile = QRectF(QPointF(tx0, ty0), QPointF(tx1, ty1));
    x1 = std::max<qreal>(tx1 + 44, SPEED_ROW_MIN_RIGHT);
    if (!in.offset.isEmpty()) {
      const qreal bw = QFontMetricsF(font(20, QFont::Bold)).horizontalAdvance(in.offset) + 18;
      const qreal bx = tx1 - 4, by = std::max(ty0 + 2, y0 + 22);
      g.badge = QRectF(bx - bw / 2, by - 15, bw, 30);
    }
  }
  g.capsule = QRectF(QPointF(EDGE, y0), QPointF(x1, y1));
  g.rec_center = QPointF(REC_CX, REC_CY);
  return g;
}

QRectF maxSlotRect() {
  return QRectF(QPointF(EDGE + 6, SPEED_ROW_TOP + 6), QPointF(DIV_1 - 6, SPEED_ROW_TOP + SPEED_ROW_HEIGHT - 6));
}

void paintCurveGlyph(QPainter &p, const QPointF &c, qreal size, const QColor &color, bool left, qreal stroke) {
  const qreal sgn = left ? -1.0 : 1.0;
  const qreal R = size * 0.30;
  const qreal stem = c.x() - sgn * size * 0.16;
  const qreal top = c.y() + size * 0.06;
  QPainterPath path(QPointF(stem, c.y() + size * 0.48));
  path.lineTo(stem, top);
  const qreal ccx = stem + sgn * R;
  QPointF end;
  for (int i = 1; i <= 24; ++i) {
    const qreal a = M_PI / 2 * i / 24;
    end = QPointF(ccx - sgn * R * std::cos(a), top - R * std::sin(a));
    path.lineTo(end);
  }
  p.save();
  p.setRenderHint(QPainter::Antialiasing);
  p.setBrush(Qt::NoBrush);
  p.setPen(QPen(color, stroke, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
  p.drawPath(path);
  const qreal ah = size * 0.30;
  QPolygonF head;
  head << QPointF(end.x() + sgn * ah * 0.75, end.y()) << QPointF(end.x() - sgn * 0.02 * ah, end.y() - ah * 0.55)
       << QPointF(end.x() - sgn * 0.02 * ah, end.y() + ah * 0.55);
  p.setPen(Qt::NoPen);
  p.setBrush(color);
  p.drawPolygon(head);
  p.restore();
}

SpeedRowGeometry paintSpeedRow(QPainter &p, const SpeedRowInputs &in) {
  const SpeedRowGeometry g = speedRowGeometry(in);
  const qreal y0 = g.capsule.top(), y1 = g.capsule.bottom();

  p.save();
  p.setRenderHints(QPainter::Antialiasing | QPainter::TextAntialiasing);

  if (in.traffic_mode) {
    paintPanel(p, g.capsule, CAP_RADIUS, PANEL, QColor(201, 34, 49), 5);
  } else {
    paintPanel(p, g.capsule, CAP_RADIUS);
  }

  // MAX (cluster set speed), or the Curve Speed Controller slot while it is lowering the speed
  static const QColor CSC_AMBER(255, 176, 32);
  if (in.csc_active) {
    const QRectF slot = maxSlotRect();
    p.setPen(QPen(QColor(255, 176, 32, 210), 3));
    p.setBrush(QColor(255, 176, 32, 46));
    p.drawRoundedRect(slot, 38, 38);
    if (!in.csc_label.isEmpty()) {
      paintCurveGlyph(p, QPointF(COL_MAX, y0 + 42), 42, CSC_AMBER, in.csc_left, 7);
      p.setFont(font(64, QFont::DemiBold));
      p.setPen(CSC_AMBER);
      drawCentredBaseline(p, COL_MAX, BASELINE + 8, in.csc_speed);
      p.setFont(font(26, QFont::DemiBold));
      p.setPen(QColor(255, 205, 110, 245));
      drawCentredBaseline(p, COL_MAX, LABEL_BASELINE + 8, in.csc_label);
    } else {
      // target == N: glyph + number only
      paintCurveGlyph(p, QPointF(COL_MAX, y0 + 50), 46, CSC_AMBER, in.csc_left, 7.5);
      p.setFont(font(70, QFont::DemiBold));
      p.setPen(CSC_AMBER);
      drawCentredBaseline(p, COL_MAX, BASELINE + 26, in.csc_speed);
    }
  } else {
    if (in.csc_training) {
      const qreal k = std::clamp(in.csc_pulse, 0.0, 1.0);
      p.setPen(QPen(QColor(255, 176, 32, int(70 + 140 * k)), 2 + k));
      p.setBrush(Qt::NoBrush);
      p.drawRoundedRect(maxSlotRect(), 38, 38);
      paintCurveGlyph(p, QPointF(COL_MAX, y0 + 42), 38, QColor(255, 176, 32, 200), in.csc_left, 6);
    }
    if (in.show_max || in.csc_training) {
      p.setFont(font(SIDE_PX, QFont::DemiBold));
      p.setPen(in.set_speed_color);
      drawCentredBaseline(p, COL_MAX, in.csc_training ? BASELINE + 8 : BASELINE, in.set_speed);
      p.setFont(font(in.csc_training ? 24 : LABEL_PX, QFont::DemiBold));
      p.setPen(in.csc_training ? QColor(255, 205, 110, 220) : in.max_color);
      drawCentredBaseline(p, COL_MAX, in.csc_training ? LABEL_BASELINE + 8 : LABEL_BASELINE,
                          in.csc_training ? in.csc_label : spaced(in.max_label));
    }
  }

  // current speed
  if (in.show_speed) {
    p.setFont(font(BIG_PX, QFont::Bold));
    p.setPen(QColor(255, 255, 255));
    drawCentredBaseline(p, COL_SPEED, BASELINE, in.speed);
    p.setFont(font(LABEL_PX, QFont::DemiBold));
    p.setPen(MUTED);
    drawCentredBaseline(p, COL_SPEED, LABEL_BASELINE, spaced(in.unit.toUpper()));
  }

  p.setPen(QPen(QColor(255, 255, 255, 36), 2));
  p.drawLine(QPointF(DIV_1, y0 + 40), QPointF(DIV_1, y1 - 40));
  if (in.show_limit) {
    p.drawLine(QPointF(DIV_2, y0 + 40), QPointF(DIV_2, y1 - 40));
  }

  // LIMIT tile (US) or round sign (EU)
  if (in.show_limit) {
    p.save();
    p.setOpacity(in.limit_opacity);
    if (in.vienna) {
      p.setPen(Qt::NoPen);
      p.setBrush(QColor(255, 255, 255));
      p.drawEllipse(g.tile);
      p.setPen(QPen(QColor(220, 30, 30), 13));
      p.setBrush(Qt::NoBrush);
      p.drawEllipse(g.tile.adjusted(9, 9, -9, -9));
      p.setPen(SIGN_INK);
      p.setFont(font(in.limit.size() >= 3 ? 46 : 56, QFont::Bold));
      p.drawText(g.tile, Qt::AlignCenter, in.limit);
    } else {
      p.setPen(QPen(SIGN_EDGE, 3));
      p.setBrush(SIGN_FILL);
      p.drawRoundedRect(g.tile, 20, 20);

      // centre the LIMIT + number pair on their actual ink bounds
      const QFont lf = font(TILE_LABEL_PX, QFont::Bold), nf = font(SIDE_PX, QFont::Bold);
      const QRectF lb = QFontMetricsF(lf).tightBoundingRect(in.limit_label);
      const QRectF nb = QFontMetricsF(nf).tightBoundingRect(in.limit);
      const qreal gap = 10;
      const qreal top = g.tile.center().y() - (lb.height() + gap + nb.height()) / 2;
      p.setFont(lf);
      p.setPen(SIGN_LABEL);
      drawCentredBaseline(p, COL_LIMIT, top - lb.top(), in.limit_label);
      p.setFont(nf);
      p.setPen(SIGN_INK);
      drawCentredBaseline(p, COL_LIMIT, top + lb.height() + gap - nb.top(), in.limit);
    }
    p.restore();

    // +offset badge on the tile corner, inside the capsule
    if (!g.badge.isEmpty()) {
      p.setPen(QPen(QColor(14, 17, 22), 2));
      p.setBrush(BADGE_GREEN);
      p.drawRoundedRect(g.badge, 15, 15);
      p.setFont(font(20, QFont::Bold));
      p.setPen(QColor(255, 255, 255));
      drawCentredBaseline(p, g.badge.center().x(), g.badge.center().y() + 7, in.offset);
    }
  }

  p.restore();
  return g;
}

// ---------------- personality pill ----------------

void paintPersonalityPill(QPainter &p, const QRectF &pill, int personality, bool traffic_mode, const QString &label) {
  static const QColor TRAFFIC_RED(232, 70, 80);
  static const int BARS[3] = {1, 2, 3};   // aggressive, standard, relaxed: more bars = longer gap

  p.save();
  p.setRenderHints(QPainter::Antialiasing | QPainter::TextAntialiasing);

  const qreal r = pill.height() / 2;
  paintPanel(p, pill, r);

  p.setFont(font(24, QFont::DemiBold));
  p.setPen(traffic_mode ? TRAFFIC_RED : QColor(255, 255, 255, 200));
  p.drawText(QRectF(pill.left(), pill.top() - PILL_LABEL_SPACE, pill.width(), PILL_LABEL_SPACE - 4), Qt::AlignCenter, label.toUpper());

  const int active = traffic_mode ? 0 : std::clamp(personality, 0, 2);
  // inner parts keep the original 252x92 pill's proportions, scaled by PILL_H / 92 (~1.63)
  const qreal seg = (pill.width() - 26) / 3;
  for (int i = 0; i < 3; ++i) {
    const qreal sx0 = pill.left() + 13 + i * seg, sx1 = sx0 + seg;
    const bool on = i == active;
    if (on) {
      p.setPen(Qt::NoPen);
      p.setBrush(traffic_mode ? QColor(TRAFFIC_RED.red(), TRAFFIC_RED.green(), TRAFFIC_RED.blue(), 235) : QColor(240, 240, 240, 235));
      const QRectF hl(QPointF(sx0 + 3, pill.top() + 13), QPointF(sx1 - 3, pill.bottom() - 13));
      p.drawRoundedRect(hl, hl.height() / 2, hl.height() / 2);
    }
    p.setPen(Qt::NoPen);
    p.setBrush(on ? QColor(20, 20, 20) : QColor(255, 255, 255, 150));
    const int nb = BARS[i];
    const qreal mx = (sx0 + sx1) / 2;
    for (int k = 0; k < nb; ++k) {
      const qreal yb = pill.center().y() - (nb - 1) * 13 + k * 26;
      p.drawRoundedRect(QRectF(mx - 29, yb - 6.5, 58, 13), 6.5, 6.5);
    }
  }
  p.restore();
}

int personalityAt(const QRectF &pill, const QPointF &pos) {
  if (!pill.adjusted(-6, -PILL_LABEL_SPACE, 6, 10).contains(pos)) return -1;
  const qreal seg = (pill.width() - 26) / 3;
  return std::clamp(int((pos.x() - pill.left() - 13) / seg), 0, 2);
}

// ---------------- lead lock-on box ----------------

QRectF leadLockBox(const QPointF &contact, float d_rel, qreal max_x, qreal max_y) {
  const qreal sz = std::clamp(750.0 / (d_rel / 3.0 + 30.0), 15.0, 30.0) * 2.35;
  const qreal w = sz * 3.2, h = w * 0.86;
  const qreal cx = std::clamp(contact.x(), w / 2 + 8, max_x - w / 2 - 8);
  const qreal bottom = std::min(contact.y() + h * 0.1, max_y - 8);
  return QRectF(cx - w / 2, bottom - h, w, h);
}

namespace {

// One label pill: number + lighter unit, vertically centred on the digits' cap height, clamped inside view
QRectF paintLabelPill(QPainter &p, qreal cx, qreal cy, qreal h, qreal pad, const QString &number, int num_px, const QColor &num_color,
                      const QString &unit, int unit_px, const QRectF &view, const QColor &accent = QColor()) {
  const QFont nf = font(num_px, QFont::Bold), uf = font(unit_px, QFont::DemiBold);
  const QString u = " " + unit;
  const qreal nw = QFontMetricsF(nf).horizontalAdvance(number), uw = QFontMetricsF(uf).horizontalAdvance(u);
  const qreal w = nw + uw + 2 * pad;
  qreal x0 = cx - w / 2;
  x0 = std::max(x0, view.left() + 8);
  x0 = std::min(x0, view.right() - 8 - w);
  const QRectF r(x0, cy - h / 2, w, h);
  p.setPen(Qt::NoPen);
  p.setBrush(QColor(20, 22, 26, 205));
  p.drawRoundedRect(r, h / 2, h / 2);
  if (accent.isValid()) {
    p.setBrush(accent);
    p.drawRoundedRect(QRectF(x0 + pad, r.bottom() - 7, nw + uw, 4), 2, 2);
  }
  const qreal baseline = cy + QFontMetricsF(nf).capHeight() / 2;
  p.setFont(nf);
  p.setPen(num_color);
  p.drawText(QPointF(x0 + pad, baseline), number);
  p.setFont(uf);
  p.setPen(MUTED);
  p.drawText(QPointF(x0 + pad + nw, baseline), u);
  return r;
}

}  // namespace

bool paintLeadLabels(QPainter &p, const QRectF &box, const LeadLabels &l, const QRectF &view, qreal keepout_top) {
  constexpr qreal GAP = 8 + 14;          // bracket thickness + spacing, as for the old distance pill
  constexpr qreal SPEED_H = 62, TAG_H = 46, STACK_GAP = 8;
  const qreal cx = box.center().x();
  const QColor speed_color = l.vision_only ? QColor(255, 255, 255, 150) : QColor(255, 255, 255);
  const bool stacked = box.bottom() + GAP + TAG_H > keepout_top;

  p.save();
  p.setRenderHints(QPainter::Antialiasing | QPainter::TextAntialiasing);
  if (stacked) {
    const qreal tag_cy = box.top() - GAP - TAG_H / 2;
    paintLabelPill(p, cx, tag_cy, TAG_H, 18, l.dist, 30, QColor(255, 255, 255), l.dist_unit, 22, view);
    const qreal speed_cy = tag_cy - TAG_H / 2 - STACK_GAP - SPEED_H / 2;
    paintLabelPill(p, cx, speed_cy, SPEED_H, 22, l.speed, 40, speed_color, l.speed_unit, 26, view, l.accent);
  } else {
    paintLabelPill(p, cx, box.top() - GAP - SPEED_H / 2, SPEED_H, 22, l.speed, 40, speed_color, l.speed_unit, 26, view, l.accent);
    paintLabelPill(p, cx, box.bottom() + GAP + TAG_H / 2, TAG_H, 18, l.dist, 30, QColor(255, 255, 255), l.dist_unit, 22, view);
  }
  p.restore();
  return stacked;
}

void paintLeadLock(QPainter &p, const QRectF &box, const QString &dist, const QColor &color) {
  const qreal thick = 8, thin = 3.5, r = 9, leg = 0.30;
  const QRectF centre = box.adjusted(-thick / 2, -thick / 2, thick / 2, thick / 2);
  const qreal cr = r + thick / 2;

  QPainterPath corners;
  const qreal lw = box.width() * leg, lh = box.height() * leg, o = thick * 2;
  corners.addRect(QRectF(QPointF(box.left() - o, box.top() - o), QPointF(box.left() + lw, box.top() + lh)));
  corners.addRect(QRectF(QPointF(box.right() - lw, box.top() - o), QPointF(box.right() + o, box.top() + lh)));
  corners.addRect(QRectF(QPointF(box.left() - o, box.bottom() - lh), QPointF(box.left() + lw, box.bottom() + o)));
  corners.addRect(QRectF(QPointF(box.right() - lw, box.bottom() - lh), QPointF(box.right() + o, box.bottom() + o)));

  p.save();
  p.setRenderHint(QPainter::Antialiasing);
  p.setBrush(Qt::NoBrush);

  auto ring = [&](qreal w, const QColor &c, bool clipped) {
    p.save();
    if (clipped) p.setClipPath(corners, Qt::IntersectClip);
    p.setPen(QPen(c, w, Qt::SolidLine, Qt::FlatCap, Qt::RoundJoin));
    p.drawRoundedRect(centre, cr, cr);
    p.restore();
  };
  // soft shadow (two widened passes stand in for the mockup's blur)
  for (const qreal grow : {6.0, 3.0}) {
    const QColor sh(0, 0, 0, grow > 4 ? 40 : 60);
    ring(thin + grow, sh, false);
    ring(thick + grow, sh, true);
  }
  ring(thin, color, false);
  ring(thick, color, true);

  if (!dist.isEmpty()) {
    const QFont f = font(38, QFont::Bold);
    const qreal tw = QFontMetricsF(f).horizontalAdvance(dist);
    const qreal px = box.center().x(), py = box.top() - thick - 14 - 30;
    const QRectF pill(px - tw / 2 - 22, py - 30, tw + 44, 60);
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(20, 22, 26, 205));
    p.drawRoundedRect(pill, 30, 30);
    p.setFont(f);
    p.setPen(QColor(255, 255, 255));
    p.drawText(pill, Qt::AlignCenter, dist);
  }
  p.restore();
}

// ---------------- round buttons ----------------

void paintRecordButton(QPainter &p, const QRectF &hit, bool recording, qreal pulse) {
  // disc of REC_DIAMETER (or the hit rect if smaller) centred in the touch target; dot / stop square scale with it
  const QPointF c = hit.center();
  const qreal d = std::min<qreal>(REC_DIAMETER, std::min(hit.width(), hit.height()));
  const QRectF r(c.x() - d / 2, c.y() - d / 2, d, d);
  const qreal dot = d * 0.19, sq = d * 0.35;
  p.save();
  p.setRenderHint(QPainter::Antialiasing);
  if (recording) {
    QColor glow(225, 60, 60);
    glow.setAlphaF(0.4 + 0.6 * std::clamp(pulse, 0.0, 1.0));
    p.setBrush(QColor(14, 17, 22, 190));
    p.setPen(QPen(glow, 5));
    p.drawEllipse(r.adjusted(3, 3, -3, -3));
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(225, 60, 60, 235));
    p.drawRoundedRect(QRectF(c.x() - sq / 2, c.y() - sq / 2, sq, sq), 7, 7);
  } else {
    p.setBrush(QColor(14, 17, 22, 190));
    p.setPen(QPen(QColor(255, 255, 255, 60), 3));
    p.drawEllipse(r.adjusted(2, 2, -2, -2));
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(225, 60, 60, 240));
    p.drawEllipse(c, dot, dot);
  }
  p.restore();
}

void paintIconButton(QPainter &p, const QRectF &r, const QPixmap &icon, qreal opacity) {
  p.save();
  p.setRenderHints(QPainter::Antialiasing | QPainter::SmoothPixmapTransform);
  p.setPen(Qt::NoPen);
  p.setBrush(PANEL_DARK);
  p.drawEllipse(r);
  p.setOpacity(opacity);
  p.drawPixmap(QPointF(r.center().x() - icon.width() / 2.0, r.center().y() - icon.height() / 2.0), icon);
  p.restore();
}

// ---------------- alert banner ----------------

QRect alertBannerRect(const QSize &widget, bool mid) {
  const int h = mid ? 156 : 110;
  const int bottom = widget.height() - 186;   // screen y 864: clears the raised steering arc (arc B)
  if (widget.width() >= 1800) {
    return QRect(QPoint(690, bottom - h), QPoint(1630, bottom));   // left edge clears the map button's top (round 3b)
  }
  return QRect(40, bottom - h, widget.width() - 80, h);
}

void paintAlertBanner(QPainter &p, const QRect &r, bool mid, const QString &text1, const QString &text2, const QColor &fill) {
  p.save();
  p.setRenderHints(QPainter::Antialiasing | QPainter::TextAntialiasing);
  paintPanel(p, r, 30, fill, STROKE, 2);

  auto fitted = [&](const QString &text, int px, QFont::Weight w) {
    QFont f = font(px, w);
    const qreal max_w = r.width() - 60;
    const qreal tw = QFontMetricsF(f).horizontalAdvance(text);
    if (tw > max_w) f.setPixelSize(std::max(24, int(px * max_w / tw)));
    return f;
  };

  p.setPen(TEXT);
  if (mid) {
    p.setFont(fitted(text1, 54, QFont::Bold));
    p.drawText(QRect(r.left(), r.top() + 18, r.width(), 80), Qt::AlignCenter, text1);
    p.setFont(fitted(text2, 30, QFont::Medium));
    p.setPen(QColor(255, 255, 255, 200));
    p.drawText(QRect(r.left(), r.top() + 92, r.width(), 42), Qt::AlignCenter, text2);
  } else {
    p.setFont(fitted(text1, 54, QFont::Bold));
    p.drawText(r, Qt::AlignCenter, text1);
  }
  p.restore();
}

}  // namespace bogpilot
