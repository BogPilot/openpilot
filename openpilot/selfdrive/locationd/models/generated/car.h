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
void car_err_fun(double *nom_x, double *delta_x, double *out_9155965617354986968);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_2871414695186438168);
void car_H_mod_fun(double *state, double *out_8509207105295575047);
void car_f_fun(double *state, double dt, double *out_4836537562228931990);
void car_F_fun(double *state, double dt, double *out_6757899816353951324);
void car_h_25(double *state, double *unused, double *out_5636842392341776803);
void car_H_25(double *state, double *unused, double *out_8171721720410462967);
void car_h_24(double *state, double *unused, double *out_8501700083487156086);
void car_H_24(double *state, double *unused, double *out_2856630719622161756);
void car_h_30(double *state, double *unused, double *out_583534790505237166);
void car_H_30(double *state, double *unused, double *out_8042382773267222897);
void car_h_26(double *state, double *unused, double *out_19781094171240351);
void car_H_26(double *state, double *unused, double *out_8828575784520774871);
void car_h_27(double *state, double *unused, double *out_635169124680931158);
void car_H_27(double *state, double *unused, double *out_5867619461466797986);
void car_h_29(double *state, double *unused, double *out_8398434381501603599);
void car_H_29(double *state, double *unused, double *out_8552614117581615081);
void car_h_28(double *state, double *unused, double *out_3239574445489628809);
void car_H_28(double *state, double *unused, double *out_3470215100512084507);
void car_h_31(double *state, double *unused, double *out_2859818288921963189);
void car_H_31(double *state, double *unused, double *out_8202367682287423395);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}