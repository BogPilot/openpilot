#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_5934457951643849053);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_3684767865165890908);
void pose_H_mod_fun(double *state, double *out_6516592031989874719);
void pose_f_fun(double *state, double dt, double *out_357987265400787918);
void pose_F_fun(double *state, double dt, double *out_6247644819371348210);
void pose_h_4(double *state, double *unused, double *out_1318227695036795702);
void pose_H_4(double *state, double *unused, double *out_3242369953198925466);
void pose_h_10(double *state, double *unused, double *out_3597588542648254460);
void pose_H_10(double *state, double *unused, double *out_8062556672432655720);
void pose_h_13(double *state, double *unused, double *out_6604511232793618697);
void pose_H_13(double *state, double *unused, double *out_7593742912193925221);
void pose_h_14(double *state, double *unused, double *out_1750689771247766537);
void pose_H_14(double *state, double *unused, double *out_7205610809538409995);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}