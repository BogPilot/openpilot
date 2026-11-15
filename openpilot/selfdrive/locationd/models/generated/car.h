#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_err_fun(double *nom_x, double *delta_x, double *out_8321129926226555584);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_6139682872100928343);
void car_H_mod_fun(double *state, double *out_34076242180925360);
void car_f_fun(double *state, double dt, double *out_2158642534494546935);
void car_F_fun(double *state, double dt, double *out_5954463895015124794);
void car_h_25(double *state, double *unused, double *out_2719516181999733219);
void car_H_25(double *state, double *unused, double *out_1270262868011046260);
void car_h_24(double *state, double *unused, double *out_70937688792751635);
void car_H_24(double *state, double *unused, double *out_4541122763011730705);
void car_h_30(double *state, double *unused, double *out_7963962634889145956);
void car_H_30(double *state, double *unused, double *out_1399601815154286330);
void car_h_26(double *state, double *unused, double *out_4724796524826667704);
void car_H_26(double *state, double *unused, double *out_613408803900734356);
void car_h_27(double *state, double *unused, double *out_5308597199970421718);
void car_H_27(double *state, double *unused, double *out_3574365126954711241);
void car_h_29(double *state, double *unused, double *out_5481108171159560015);
void car_H_29(double *state, double *unused, double *out_889370470839894146);
void car_h_28(double *state, double *unused, double *out_346217202289128486);
void car_H_28(double *state, double *unused, double *out_5971769487909424720);
void car_h_31(double *state, double *unused, double *out_7845955240955769212);
void car_H_31(double *state, double *unused, double *out_1239616906134085832);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}