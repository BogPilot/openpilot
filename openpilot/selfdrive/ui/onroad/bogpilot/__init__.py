"""BogPilot onroad HUD (raylib port of the BogPilot/FrogPilot Qt onroad redesign, bogpilot-tesla 367e1fe).

Coordinates follow the Qt widget space: the screen minus the 30 px engage border, i.e. the content rect
passed to the onroad renderers. Every drawing helper takes an `ox, oy` origin (content_rect.x / .y).
"""
