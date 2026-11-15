#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_7638121806024428864);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_7875098923290555577);
void pose_H_mod_fun(double *state, double *out_8951288927873865647);
void pose_f_fun(double *state, double dt, double *out_7132983660684650866);
void pose_F_fun(double *state, double dt, double *out_5301626584540277716);
void pose_h_4(double *state, double *unused, double *out_1649115856604052289);
void pose_H_4(double *state, double *unused, double *out_7039102026818812520);
void pose_h_10(double *state, double *unused, double *out_1675122934588286079);
void pose_H_10(double *state, double *unused, double *out_8074540264726699631);
void pose_h_13(double *state, double *unused, double *out_5348779440595545487);
void pose_H_13(double *state, double *unused, double *out_3826828201486479719);
void pose_h_14(double *state, double *unused, double *out_8398073438339046034);
void pose_H_14(double *state, double *unused, double *out_3075861170479327991);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}