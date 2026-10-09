// BogPilot steering arc. QPainter port of upstream openpilot selfdrive/ui/mici/onroad/torque_bar.py (MIT);
// see steering_arc.h for the licence and the list of BogPilot changes.
#include "frogpilot/ui/qt/onroad/steering_arc.h"

#include <algorithm>
#include <cmath>
#include <vector>

#include <QLinearGradient>
#include <QPainterPath>

namespace {

constexpr float GRAVITY = 9.81f;
constexpr float FILTER_K = (0.05f / 0.1f) / (1.0f + 0.05f / 0.1f);   // FirstOrderFilter(rc 0.1 s, dt 1/20 s)
constexpr int CAP_SEGS = 10;
constexpr int MAX_ARC_SEGS = 64;

const QColor WHITE(255, 255, 255);
const QColor PURPLE(150, 100, 255);
const QColor YELLOW(255, 200, 0);
const QColor ORANGE(255, 115, 0);
const QColor DOT_GREY(182, 182, 182);

float interp(float x, float x0, float x1, float y0, float y1) {
  if (x <= x0) return y0;
  if (x >= x1) return y1;
  return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
}

float rad(float deg) { return deg * float(M_PI) / 180.0f; }

QColor withAlpha(QColor c, float a) {
  c.setAlphaF(std::clamp(a, 0.0f, 1.0f));
  return c;
}

QColor blend(const QColor &a, const QColor &b, float k) {
  k = std::clamp(k, 0.0f, 1.0f);
  return QColor::fromRgbF(a.redF() + (b.redF() - a.redF()) * k, a.greenF() + (b.greenF() - a.greenF()) * k,
                          a.blueF() + (b.blueF() - a.blueF()) * k, a.alphaF() + (b.alphaF() - a.alphaF()) * k);
}

// One rounded end of the thick arc (upstream get_cap): a quarter circle at the outer corner and one at the inner corner.
void appendCap(std::vector<QPointF> &out, bool left, float a_deg, float r_mid, float half, float cap) {
  const float nx = std::cos(rad(a_deg)), ny = std::sin(rad(a_deg));   // outward normal
  const float tx = -ny, ty = nx;                                        // tangent (CCW)
  const float mx = nx * r_mid, my = ny * r_mid;

  std::vector<QPointF> top, bottom;
  const float ex = mx + nx * (half - cap), ey = my + ny * (half - cap);
  for (int i = 1; i <= CAP_SEGS; ++i) {            // linspace(..., CAP_SEGS + 2)[1:-1]
    const float f = float(i) / (CAP_SEGS + 1);
    const float a = rad(left ? 180.0f - 90.0f * f : 90.0f - 90.0f * f);
    top.emplace_back(ex + std::cos(a) * cap * tx + std::sin(a) * cap * nx, ey + std::cos(a) * cap * ty + std::sin(a) * cap * ny);
  }
  const float ex2 = mx + nx * (-half + cap), ey2 = my + ny * (-half + cap);
  for (int i = 0; i < CAP_SEGS; ++i) {             // linspace(..., CAP_SEGS + 1)[:-1]
    const float f = float(i) / CAP_SEGS;
    const float a = rad(left ? -90.0f - 90.0f * f : -90.0f * f);
    bottom.emplace_back(ex2 + std::cos(a) * cap * tx + std::sin(a) * cap * nx, ey2 + std::cos(a) * cap * ty + std::sin(a) * cap * ny);
  }
  const std::vector<QPointF> &first = left ? bottom : top, &second = left ? top : bottom;
  out.insert(out.end(), first.begin(), first.end());
  out.insert(out.end(), second.begin(), second.end());
}

}  // namespace

QPolygonF SteeringArc::arcBarPolygon(float r_mid, float thickness, float a0_deg, float a1_deg, float cap_radius) {
  if (a1_deg < a0_deg) std::swap(a0_deg, a1_deg);
  const float half = thickness * 0.5f;
  const float cap = std::min(cap_radius, half);
  const float span = std::max(1e-3f, a1_deg - a0_deg);
  const int segs = std::clamp(int(r_mid * rad(span) / 2.0f), 6, MAX_ARC_SEGS);

  std::vector<QPointF> pts;
  pts.reserve(2 * (segs + 1) + 4 * CAP_SEGS + 1);
  for (int i = 0; i <= segs; ++i) {   // outer arc a0 -> a1
    const float a = rad(a0_deg + (a1_deg - a0_deg) * i / segs);
    pts.emplace_back(std::cos(a) * (r_mid + half), std::sin(a) * (r_mid + half));
  }
  appendCap(pts, false, a1_deg, r_mid, half, cap);
  for (int i = 0; i <= segs; ++i) {   // inner arc a1 -> a0
    const float a = rad(a1_deg + (a0_deg - a1_deg) * i / segs);
    pts.emplace_back(std::cos(a) * (r_mid - half), std::sin(a) * (r_mid - half));
  }
  appendCap(pts, true, a0_deg, r_mid, half, cap);
  // Qt 5.12 on the device has no QVector(iterator, iterator) constructor
  QPolygonF poly;
  poly.reserve(static_cast<int>(pts.size()));
  for (const QPointF &pt : pts) poly << pt;
  return poly;
}

float SteeringArc::angleUtilization(float curvature, float desired_curvature, float v_ego, float roll, float max_lat_accel) {
  const float actual = curvature * v_ego * v_ego;
  const float desired = desired_curvature * v_ego * v_ego;
  const float roll_compensation = roll * GRAVITY * interp(v_ego, 5.0f, 15.0f, 0.0f, 1.0f);
  const float max_lat = max_lat_accel > 0.1f ? max_lat_accel : DEFAULT_MAX_LAT_ACCEL;
  return -std::clamp((actual - roll_compensation + (desired - actual)) / max_lat, -1.0f, 1.0f);
}

void SteeringArc::update(float utilization, bool lat_active, bool active, bool engaged_colors, bool experimental) {
  const float target = lat_active ? std::clamp(utilization, -1.0f, 1.0f) : 0.0f;
  torque_ = (1.0f - FILTER_K) * torque_ + FILTER_K * target;
  alpha_ = (1.0f - FILTER_K) * alpha_ + FILTER_K * (active ? 1.0f : 0.55f);
  engaged_colors_ = engaged_colors;
  experimental_ = experimental;
}

QRectF SteeringArc::tapRect(const QRect &view) const {
  const float r_mid = 1200 * SCALE + 8.5f * SCALE / 2;
  const float hw = r_mid * std::sin(rad(SPAN_DEG / 2)) + 30;
  const float cx = view.left() + view.width() / 2.0f;
  return QRectF(cx - hw, view.bottom() + 1 - 150, 2 * hw, 150);
}

void SteeringArc::paint(QPainter &p, const QRect &view) const {
  const float s = SCALE;
  const float at = std::fabs(torque_);
  const float alpha = std::max(alpha_, 0.05f);
  const float offset = interp(at, 0.5f, 1.0f, 22 * s, 26 * s);
  const float thickness = interp(at, 0.5f, 1.0f, 8.5f * s, 23 * s);   // upstream 14 -> 56 at mici scale; thinner here
  const float radius = 1200 * s;
  const float mid_r = radius + thickness / 2;
  const float cx = view.left() + view.width() / 2.0f;
  const float cy = view.bottom() + 1 + radius - offset;
  const float top = -90.0f;
  const QColor base = experimental_ ? PURPLE : WHITE;

  p.save();
  p.setRenderHint(QPainter::Antialiasing);
  p.translate(cx, cy);

  // track (+ a faint dark edge so it reads over a bright path)
  const QPolygonF bg = arcBarPolygon(mid_r, thickness, top - SPAN_DEG / 2, top + SPAN_DEG / 2, 7 * s);
  float bg_alpha = interp(at, 0.5f, 1.0f, 0.25f, 0.5f) * alpha;
  if (!engaged_colors_) bg_alpha = 0.15f * alpha;
  // soft dark halo (stacked round-joined strokes stand in for the mockup's blur)
  p.setBrush(Qt::NoBrush);
  for (const int w : {28, 24, 20, 16, 12, 8, 4}) {
    p.setPen(QPen(QColor(0, 0, 0, int(9 * alpha)), w, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
    p.drawPolygon(bg);
  }
  p.setPen(Qt::NoPen);
  p.setBrush(withAlpha(WHITE, bg_alpha));
  p.drawPolygon(bg);

  // fill from the centre toward the steer side
  if (at > 0.005f) {
    const QPolygonF fill = arcBarPolygon(mid_r, thickness, top, top + SPAN_DEG / 2 * torque_, 7 * s);
    const float k = std::max(0.0f, at - 0.75f) * 4.0f;
    QColor c0 = blend(withAlpha(base, 0.9f * alpha), withAlpha(experimental_ ? PURPLE : YELLOW, alpha), k);
    QColor c1 = blend(withAlpha(base, 0.9f * alpha), withAlpha(ORANGE, alpha), k);
    if (!engaged_colors_) c0 = c1 = withAlpha(WHITE, 0.35f * alpha);
    const qreal edge = torque_ < 0 ? bg.boundingRect().left() : bg.boundingRect().right();
    QLinearGradient g(0, 0, edge * 0.65, 0);
    g.setColorAt(0.0, c0);
    g.setColorAt(1.0, c1);
    p.setBrush(g);
    p.drawPolygon(fill);
  }

  // centre dot
  if (at < 0.5f) {
    const float dot_y = -radius - thickness / 2;   // on the centreline: screen y = bottom - offset - thickness / 2
    p.setBrush(withAlpha(DOT_GREY, 0.9f * alpha));
    p.drawEllipse(QPointF(0, dot_y), 5 * s, 5 * s);
  }
  p.restore();
}
