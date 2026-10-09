/**
The MIT License

Copyright (c) 2018, Comma.ai, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

BogPilot steering arc: a QPainter port of upstream openpilot's comma four torque bar
(selfdrive/ui/mici/onroad/torque_bar.py, MIT): rounded thick-arc polygon (arc_bar_pts), first-order
filtered lateral utilisation, thickness/offset growth past 50 %, centre-to-65 % gradient that blends to
yellow/orange past 75 %, and the grey centre dot below 50 %. BogPilot changes: 14 degree span, 2.6x scale
for the 2160 px screen, purple in Experimental Mode, stays visible (dimmed) while disengaged because it is
also the Experimental Mode tap target, and the fill grows toward the turn direction.
***/
#pragma once

#include <QPainter>
#include <QPolygonF>
#include <QRect>
#include <QRectF>

class SteeringArc {
public:
  static constexpr float SPAN_DEG = 14.0f;
  static constexpr float SCALE = 2.6f;
  static constexpr float DEFAULT_MAX_LAT_ACCEL = 3.0f;  // m/s^2

  // utilization in [-1, 1]; negative fills left. lat_active=false decays the fill to zero.
  // active: openpilot engaged in any form (track at full strength). engaged_colors: engaged / lateral-only
  // (white or purple fill); otherwise the fill is drawn faded white like upstream.
  void update(float utilization, bool lat_active, bool active, bool engaged_colors, bool experimental);
  void setFilteredValue(float v) { torque_ = v; }   // demos / tests
  float value() const { return torque_; }

  void paint(QPainter &p, const QRect &view) const;
  // Generous tap target around the arc (replaces the removed top-right wheel button)
  QRectF tapRect(const QRect &view) const;

  // Upstream utilisation for angle / curvature lateral control:
  // (curvature*v^2 - roll*g*interp(v,[5,15],[0,1]) + (desired - actual lateral accel)) / maxLateralAccel,
  // negated so a left turn (positive curvature) fills to the left.
  static float angleUtilization(float curvature, float desired_curvature, float v_ego, float roll, float max_lat_accel);

  // Rounded thick-arc polygon centred on the origin (upstream arc_bar_pts), angles in degrees, y down.
  static QPolygonF arcBarPolygon(float r_mid, float thickness, float a0_deg, float a1_deg, float cap_radius);

private:
  float torque_ = 0.0f;
  float alpha_ = 0.0f;
  bool engaged_colors_ = false;
  bool experimental_ = false;
};
