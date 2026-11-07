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
void car_err_fun(double *nom_x, double *delta_x, double *out_4975635636005312372);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_5810940517248718795);
void car_H_mod_fun(double *state, double *out_2279184306914852573);
void car_f_fun(double *state, double dt, double *out_2316200443245060609);
void car_F_fun(double *state, double dt, double *out_9022909277376252601);
void car_h_25(double *state, double *unused, double *out_7178911009583483193);
void car_H_25(double *state, double *unused, double *out_5642153726059007232);
void car_h_24(double *state, double *unused, double *out_1104138690087538503);
void car_H_24(double *state, double *unused, double *out_2227862213915952772);
void car_h_30(double *state, double *unused, double *out_408075783233132257);
void car_H_30(double *state, double *unused, double *out_8160486684566255859);
void car_h_26(double *state, double *unused, double *out_4593597484427713388);
void car_H_26(double *state, double *unused, double *out_1900650407184951008);
void car_h_27(double *state, double *unused, double *out_6266159796465222778);
void car_H_27(double *state, double *unused, double *out_5985723372765830948);
void car_h_29(double *state, double *unused, double *out_5409749050893977902);
void car_H_29(double *state, double *unused, double *out_8670718028880648043);
void car_h_28(double *state, double *unused, double *out_7209669649366885213);
void car_H_28(double *state, double *unused, double *out_3588319011811117469);
void car_h_31(double *state, double *unused, double *out_3504567807305395982);
void car_H_31(double *state, double *unused, double *out_1274442304951599532);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}