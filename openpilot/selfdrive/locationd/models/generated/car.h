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
void car_err_fun(double *nom_x, double *delta_x, double *out_6375148504099374102);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_5936432944455214487);
void car_H_mod_fun(double *state, double *out_3687612785923554437);
void car_f_fun(double *state, double dt, double *out_8923811346717442323);
void car_F_fun(double *state, double dt, double *out_1367243681225472950);
void car_h_25(double *state, double *unused, double *out_6503565297254880647);
void car_H_25(double *state, double *unused, double *out_164632135934062760);
void car_h_24(double *state, double *unused, double *out_6019772980759252960);
void car_H_24(double *state, double *unused, double *out_6410939670657455341);
void car_h_30(double *state, double *unused, double *out_4411877301205886290);
void car_H_30(double *state, double *unused, double *out_6752058205557553995);
void car_h_26(double *state, double *unused, double *out_8051942933197523573);
void car_H_26(double *state, double *unused, double *out_3906135454808118984);
void car_h_27(double *state, double *unused, double *out_3466779245810547962);
void car_H_27(double *state, double *unused, double *out_4577294893757129084);
void car_h_29(double *state, double *unused, double *out_8392136901422708491);
void car_H_29(double *state, double *unused, double *out_2863932166887578051);
void car_h_28(double *state, double *unused, double *out_8468452513471393607);
void car_H_28(double *state, double *unused, double *out_2218466850181952523);
void car_h_31(double *state, double *unused, double *out_5172343550104320033);
void car_H_31(double *state, double *unused, double *out_133986174057102332);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}