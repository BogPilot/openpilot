#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_6163145922104175593);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_2416579067635792744);
void pose_H_mod_fun(double *state, double *out_3962135837270256316);
void pose_f_fun(double *state, double dt, double *out_6578666550680470474);
void pose_F_fun(double *state, double dt, double *out_3360432821028871183);
void pose_h_4(double *state, double *unused, double *out_6216561684044621445);
void pose_H_4(double *state, double *unused, double *out_6284303352466070533);
void pose_h_10(double *state, double *unused, double *out_8921172237656055896);
void pose_H_10(double *state, double *unused, double *out_4166178305681923609);
void pose_h_13(double *state, double *unused, double *out_4225136367746162929);
void pose_H_13(double *state, double *unused, double *out_1326327855850630396);
void pose_h_14(double *state, double *unused, double *out_3049593094819758450);
void pose_H_14(double *state, double *unused, double *out_2321062496126586004);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}