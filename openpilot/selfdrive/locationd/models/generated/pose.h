#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_8954543502953545600);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_4429120357540117455);
void pose_H_mod_fun(double *state, double *out_230881002087446555);
void pose_f_fun(double *state, double dt, double *out_7515598229942337125);
void pose_F_fun(double *state, double dt, double *out_1734808733268298500);
void pose_h_4(double *state, double *unused, double *out_5738748106133999168);
void pose_H_4(double *state, double *unused, double *out_4002688211931354127);
void pose_h_10(double *state, double *unused, double *out_5469958614434535899);
void pose_H_10(double *state, double *unused, double *out_6327455986419743559);
void pose_h_13(double *state, double *unused, double *out_4757981965902022494);
void pose_H_13(double *state, double *unused, double *out_7214962037263686928);
void pose_h_14(double *state, double *unused, double *out_6416907027380241315);
void pose_H_14(double *state, double *unused, double *out_919899779635981831);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}