#include "car.h"

namespace {
#define DIM 9
#define EDIM 9
#define MEDIM 9
typedef void (*Hfun)(double *, double *, double *);

double rotational_inertia;

void set_rotational_inertia(double x){ rotational_inertia = x;}

double center_to_front;

void set_center_to_front(double x){ center_to_front = x;}

double center_to_rear;

void set_center_to_rear(double x){ center_to_rear = x;}

double stiffness_front;

void set_stiffness_front(double x){ stiffness_front = x;}

double stiffness_rear;

void set_stiffness_rear(double x){ stiffness_rear = x;}
const static double MAHA_THRESH_25 = 3.8414588206941227;
const static double MAHA_THRESH_24 = 5.991464547107981;
const static double MAHA_THRESH_30 = 3.8414588206941227;
const static double MAHA_THRESH_26 = 3.8414588206941227;
const static double MAHA_THRESH_27 = 3.8414588206941227;
const static double MAHA_THRESH_29 = 3.8414588206941227;
const static double MAHA_THRESH_28 = 3.8414588206941227;
const static double MAHA_THRESH_31 = 3.8414588206941227;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_6375148504099374102) {
   out_6375148504099374102[0] = delta_x[0] + nom_x[0];
   out_6375148504099374102[1] = delta_x[1] + nom_x[1];
   out_6375148504099374102[2] = delta_x[2] + nom_x[2];
   out_6375148504099374102[3] = delta_x[3] + nom_x[3];
   out_6375148504099374102[4] = delta_x[4] + nom_x[4];
   out_6375148504099374102[5] = delta_x[5] + nom_x[5];
   out_6375148504099374102[6] = delta_x[6] + nom_x[6];
   out_6375148504099374102[7] = delta_x[7] + nom_x[7];
   out_6375148504099374102[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_5936432944455214487) {
   out_5936432944455214487[0] = -nom_x[0] + true_x[0];
   out_5936432944455214487[1] = -nom_x[1] + true_x[1];
   out_5936432944455214487[2] = -nom_x[2] + true_x[2];
   out_5936432944455214487[3] = -nom_x[3] + true_x[3];
   out_5936432944455214487[4] = -nom_x[4] + true_x[4];
   out_5936432944455214487[5] = -nom_x[5] + true_x[5];
   out_5936432944455214487[6] = -nom_x[6] + true_x[6];
   out_5936432944455214487[7] = -nom_x[7] + true_x[7];
   out_5936432944455214487[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_3687612785923554437) {
   out_3687612785923554437[0] = 1.0;
   out_3687612785923554437[1] = 0.0;
   out_3687612785923554437[2] = 0.0;
   out_3687612785923554437[3] = 0.0;
   out_3687612785923554437[4] = 0.0;
   out_3687612785923554437[5] = 0.0;
   out_3687612785923554437[6] = 0.0;
   out_3687612785923554437[7] = 0.0;
   out_3687612785923554437[8] = 0.0;
   out_3687612785923554437[9] = 0.0;
   out_3687612785923554437[10] = 1.0;
   out_3687612785923554437[11] = 0.0;
   out_3687612785923554437[12] = 0.0;
   out_3687612785923554437[13] = 0.0;
   out_3687612785923554437[14] = 0.0;
   out_3687612785923554437[15] = 0.0;
   out_3687612785923554437[16] = 0.0;
   out_3687612785923554437[17] = 0.0;
   out_3687612785923554437[18] = 0.0;
   out_3687612785923554437[19] = 0.0;
   out_3687612785923554437[20] = 1.0;
   out_3687612785923554437[21] = 0.0;
   out_3687612785923554437[22] = 0.0;
   out_3687612785923554437[23] = 0.0;
   out_3687612785923554437[24] = 0.0;
   out_3687612785923554437[25] = 0.0;
   out_3687612785923554437[26] = 0.0;
   out_3687612785923554437[27] = 0.0;
   out_3687612785923554437[28] = 0.0;
   out_3687612785923554437[29] = 0.0;
   out_3687612785923554437[30] = 1.0;
   out_3687612785923554437[31] = 0.0;
   out_3687612785923554437[32] = 0.0;
   out_3687612785923554437[33] = 0.0;
   out_3687612785923554437[34] = 0.0;
   out_3687612785923554437[35] = 0.0;
   out_3687612785923554437[36] = 0.0;
   out_3687612785923554437[37] = 0.0;
   out_3687612785923554437[38] = 0.0;
   out_3687612785923554437[39] = 0.0;
   out_3687612785923554437[40] = 1.0;
   out_3687612785923554437[41] = 0.0;
   out_3687612785923554437[42] = 0.0;
   out_3687612785923554437[43] = 0.0;
   out_3687612785923554437[44] = 0.0;
   out_3687612785923554437[45] = 0.0;
   out_3687612785923554437[46] = 0.0;
   out_3687612785923554437[47] = 0.0;
   out_3687612785923554437[48] = 0.0;
   out_3687612785923554437[49] = 0.0;
   out_3687612785923554437[50] = 1.0;
   out_3687612785923554437[51] = 0.0;
   out_3687612785923554437[52] = 0.0;
   out_3687612785923554437[53] = 0.0;
   out_3687612785923554437[54] = 0.0;
   out_3687612785923554437[55] = 0.0;
   out_3687612785923554437[56] = 0.0;
   out_3687612785923554437[57] = 0.0;
   out_3687612785923554437[58] = 0.0;
   out_3687612785923554437[59] = 0.0;
   out_3687612785923554437[60] = 1.0;
   out_3687612785923554437[61] = 0.0;
   out_3687612785923554437[62] = 0.0;
   out_3687612785923554437[63] = 0.0;
   out_3687612785923554437[64] = 0.0;
   out_3687612785923554437[65] = 0.0;
   out_3687612785923554437[66] = 0.0;
   out_3687612785923554437[67] = 0.0;
   out_3687612785923554437[68] = 0.0;
   out_3687612785923554437[69] = 0.0;
   out_3687612785923554437[70] = 1.0;
   out_3687612785923554437[71] = 0.0;
   out_3687612785923554437[72] = 0.0;
   out_3687612785923554437[73] = 0.0;
   out_3687612785923554437[74] = 0.0;
   out_3687612785923554437[75] = 0.0;
   out_3687612785923554437[76] = 0.0;
   out_3687612785923554437[77] = 0.0;
   out_3687612785923554437[78] = 0.0;
   out_3687612785923554437[79] = 0.0;
   out_3687612785923554437[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_8923811346717442323) {
   out_8923811346717442323[0] = state[0];
   out_8923811346717442323[1] = state[1];
   out_8923811346717442323[2] = state[2];
   out_8923811346717442323[3] = state[3];
   out_8923811346717442323[4] = state[4];
   out_8923811346717442323[5] = dt*(stiffness_front*(-state[2] - state[3] + state[7])*state[0]/state[1] + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/state[4] + ((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4])*state[6] - 9.8100000000000005*state[8]) + state[5];
   out_8923811346717442323[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_8923811346717442323[7] = state[7];
   out_8923811346717442323[8] = state[8];
}
void F_fun(double *state, double dt, double *out_1367243681225472950) {
   out_1367243681225472950[0] = 1;
   out_1367243681225472950[1] = 0;
   out_1367243681225472950[2] = 0;
   out_1367243681225472950[3] = 0;
   out_1367243681225472950[4] = 0;
   out_1367243681225472950[5] = 0;
   out_1367243681225472950[6] = 0;
   out_1367243681225472950[7] = 0;
   out_1367243681225472950[8] = 0;
   out_1367243681225472950[9] = 0;
   out_1367243681225472950[10] = 1;
   out_1367243681225472950[11] = 0;
   out_1367243681225472950[12] = 0;
   out_1367243681225472950[13] = 0;
   out_1367243681225472950[14] = 0;
   out_1367243681225472950[15] = 0;
   out_1367243681225472950[16] = 0;
   out_1367243681225472950[17] = 0;
   out_1367243681225472950[18] = 0;
   out_1367243681225472950[19] = 0;
   out_1367243681225472950[20] = 1;
   out_1367243681225472950[21] = 0;
   out_1367243681225472950[22] = 0;
   out_1367243681225472950[23] = 0;
   out_1367243681225472950[24] = 0;
   out_1367243681225472950[25] = 0;
   out_1367243681225472950[26] = 0;
   out_1367243681225472950[27] = 0;
   out_1367243681225472950[28] = 0;
   out_1367243681225472950[29] = 0;
   out_1367243681225472950[30] = 1;
   out_1367243681225472950[31] = 0;
   out_1367243681225472950[32] = 0;
   out_1367243681225472950[33] = 0;
   out_1367243681225472950[34] = 0;
   out_1367243681225472950[35] = 0;
   out_1367243681225472950[36] = 0;
   out_1367243681225472950[37] = 0;
   out_1367243681225472950[38] = 0;
   out_1367243681225472950[39] = 0;
   out_1367243681225472950[40] = 1;
   out_1367243681225472950[41] = 0;
   out_1367243681225472950[42] = 0;
   out_1367243681225472950[43] = 0;
   out_1367243681225472950[44] = 0;
   out_1367243681225472950[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/state[1] + (-stiffness_front - stiffness_rear)*state[5]/state[4] + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/state[4]);
   out_1367243681225472950[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/pow(state[1], 2);
   out_1367243681225472950[47] = -dt*stiffness_front*state[0]/state[1];
   out_1367243681225472950[48] = -dt*stiffness_front*state[0]/state[1];
   out_1367243681225472950[49] = dt*(-(-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/pow(state[4], 2) + (-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/pow(state[4], 2) - 1)*state[6]);
   out_1367243681225472950[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/state[4] + 1;
   out_1367243681225472950[51] = dt*((-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/state[4] - state[4]);
   out_1367243681225472950[52] = dt*stiffness_front*state[0]/state[1];
   out_1367243681225472950[53] = -9.8100000000000005*dt;
   out_1367243681225472950[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_1367243681225472950[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_1367243681225472950[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_1367243681225472950[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_1367243681225472950[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_1367243681225472950[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_1367243681225472950[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_1367243681225472950[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_1367243681225472950[62] = 0;
   out_1367243681225472950[63] = 0;
   out_1367243681225472950[64] = 0;
   out_1367243681225472950[65] = 0;
   out_1367243681225472950[66] = 0;
   out_1367243681225472950[67] = 0;
   out_1367243681225472950[68] = 0;
   out_1367243681225472950[69] = 0;
   out_1367243681225472950[70] = 1;
   out_1367243681225472950[71] = 0;
   out_1367243681225472950[72] = 0;
   out_1367243681225472950[73] = 0;
   out_1367243681225472950[74] = 0;
   out_1367243681225472950[75] = 0;
   out_1367243681225472950[76] = 0;
   out_1367243681225472950[77] = 0;
   out_1367243681225472950[78] = 0;
   out_1367243681225472950[79] = 0;
   out_1367243681225472950[80] = 1;
}
void h_25(double *state, double *unused, double *out_6503565297254880647) {
   out_6503565297254880647[0] = state[6];
}
void H_25(double *state, double *unused, double *out_164632135934062760) {
   out_164632135934062760[0] = 0;
   out_164632135934062760[1] = 0;
   out_164632135934062760[2] = 0;
   out_164632135934062760[3] = 0;
   out_164632135934062760[4] = 0;
   out_164632135934062760[5] = 0;
   out_164632135934062760[6] = 1;
   out_164632135934062760[7] = 0;
   out_164632135934062760[8] = 0;
}
void h_24(double *state, double *unused, double *out_6019772980759252960) {
   out_6019772980759252960[0] = state[4];
   out_6019772980759252960[1] = state[5];
}
void H_24(double *state, double *unused, double *out_6410939670657455341) {
   out_6410939670657455341[0] = 0;
   out_6410939670657455341[1] = 0;
   out_6410939670657455341[2] = 0;
   out_6410939670657455341[3] = 0;
   out_6410939670657455341[4] = 1;
   out_6410939670657455341[5] = 0;
   out_6410939670657455341[6] = 0;
   out_6410939670657455341[7] = 0;
   out_6410939670657455341[8] = 0;
   out_6410939670657455341[9] = 0;
   out_6410939670657455341[10] = 0;
   out_6410939670657455341[11] = 0;
   out_6410939670657455341[12] = 0;
   out_6410939670657455341[13] = 0;
   out_6410939670657455341[14] = 1;
   out_6410939670657455341[15] = 0;
   out_6410939670657455341[16] = 0;
   out_6410939670657455341[17] = 0;
}
void h_30(double *state, double *unused, double *out_4411877301205886290) {
   out_4411877301205886290[0] = state[4];
}
void H_30(double *state, double *unused, double *out_6752058205557553995) {
   out_6752058205557553995[0] = 0;
   out_6752058205557553995[1] = 0;
   out_6752058205557553995[2] = 0;
   out_6752058205557553995[3] = 0;
   out_6752058205557553995[4] = 1;
   out_6752058205557553995[5] = 0;
   out_6752058205557553995[6] = 0;
   out_6752058205557553995[7] = 0;
   out_6752058205557553995[8] = 0;
}
void h_26(double *state, double *unused, double *out_8051942933197523573) {
   out_8051942933197523573[0] = state[7];
}
void H_26(double *state, double *unused, double *out_3906135454808118984) {
   out_3906135454808118984[0] = 0;
   out_3906135454808118984[1] = 0;
   out_3906135454808118984[2] = 0;
   out_3906135454808118984[3] = 0;
   out_3906135454808118984[4] = 0;
   out_3906135454808118984[5] = 0;
   out_3906135454808118984[6] = 0;
   out_3906135454808118984[7] = 1;
   out_3906135454808118984[8] = 0;
}
void h_27(double *state, double *unused, double *out_3466779245810547962) {
   out_3466779245810547962[0] = state[3];
}
void H_27(double *state, double *unused, double *out_4577294893757129084) {
   out_4577294893757129084[0] = 0;
   out_4577294893757129084[1] = 0;
   out_4577294893757129084[2] = 0;
   out_4577294893757129084[3] = 1;
   out_4577294893757129084[4] = 0;
   out_4577294893757129084[5] = 0;
   out_4577294893757129084[6] = 0;
   out_4577294893757129084[7] = 0;
   out_4577294893757129084[8] = 0;
}
void h_29(double *state, double *unused, double *out_8392136901422708491) {
   out_8392136901422708491[0] = state[1];
}
void H_29(double *state, double *unused, double *out_2863932166887578051) {
   out_2863932166887578051[0] = 0;
   out_2863932166887578051[1] = 1;
   out_2863932166887578051[2] = 0;
   out_2863932166887578051[3] = 0;
   out_2863932166887578051[4] = 0;
   out_2863932166887578051[5] = 0;
   out_2863932166887578051[6] = 0;
   out_2863932166887578051[7] = 0;
   out_2863932166887578051[8] = 0;
}
void h_28(double *state, double *unused, double *out_8468452513471393607) {
   out_8468452513471393607[0] = state[0];
}
void H_28(double *state, double *unused, double *out_2218466850181952523) {
   out_2218466850181952523[0] = 1;
   out_2218466850181952523[1] = 0;
   out_2218466850181952523[2] = 0;
   out_2218466850181952523[3] = 0;
   out_2218466850181952523[4] = 0;
   out_2218466850181952523[5] = 0;
   out_2218466850181952523[6] = 0;
   out_2218466850181952523[7] = 0;
   out_2218466850181952523[8] = 0;
}
void h_31(double *state, double *unused, double *out_5172343550104320033) {
   out_5172343550104320033[0] = state[8];
}
void H_31(double *state, double *unused, double *out_133986174057102332) {
   out_133986174057102332[0] = 0;
   out_133986174057102332[1] = 0;
   out_133986174057102332[2] = 0;
   out_133986174057102332[3] = 0;
   out_133986174057102332[4] = 0;
   out_133986174057102332[5] = 0;
   out_133986174057102332[6] = 0;
   out_133986174057102332[7] = 0;
   out_133986174057102332[8] = 1;
}
#include <eigen3/Eigen/Dense>
#include <iostream>

typedef Eigen::Matrix<double, DIM, DIM, Eigen::RowMajor> DDM;
typedef Eigen::Matrix<double, EDIM, EDIM, Eigen::RowMajor> EEM;
typedef Eigen::Matrix<double, DIM, EDIM, Eigen::RowMajor> DEM;

void predict(double *in_x, double *in_P, double *in_Q, double dt) {
  typedef Eigen::Matrix<double, MEDIM, MEDIM, Eigen::RowMajor> RRM;

  double nx[DIM] = {0};
  double in_F[EDIM*EDIM] = {0};

  // functions from sympy
  f_fun(in_x, dt, nx);
  F_fun(in_x, dt, in_F);


  EEM F(in_F);
  EEM P(in_P);
  EEM Q(in_Q);

  RRM F_main = F.topLeftCorner(MEDIM, MEDIM);
  P.topLeftCorner(MEDIM, MEDIM) = (F_main * P.topLeftCorner(MEDIM, MEDIM)) * F_main.transpose();
  P.topRightCorner(MEDIM, EDIM - MEDIM) = F_main * P.topRightCorner(MEDIM, EDIM - MEDIM);
  P.bottomLeftCorner(EDIM - MEDIM, MEDIM) = P.bottomLeftCorner(EDIM - MEDIM, MEDIM) * F_main.transpose();

  P = P + dt*Q;

  // copy out state
  memcpy(in_x, nx, DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
}

// note: extra_args dim only correct when null space projecting
// otherwise 1
template <int ZDIM, int EADIM, bool MAHA_TEST>
void update(double *in_x, double *in_P, Hfun h_fun, Hfun H_fun, Hfun Hea_fun, double *in_z, double *in_R, double *in_ea, double MAHA_THRESHOLD) {
  typedef Eigen::Matrix<double, ZDIM, ZDIM, Eigen::RowMajor> ZZM;
  typedef Eigen::Matrix<double, ZDIM, DIM, Eigen::RowMajor> ZDM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, EDIM, Eigen::RowMajor> XEM;
  //typedef Eigen::Matrix<double, EDIM, ZDIM, Eigen::RowMajor> EZM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, 1> X1M;
  typedef Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> XXM;

  double in_hx[ZDIM] = {0};
  double in_H[ZDIM * DIM] = {0};
  double in_H_mod[EDIM * DIM] = {0};
  double delta_x[EDIM] = {0};
  double x_new[DIM] = {0};


  // state x, P
  Eigen::Matrix<double, ZDIM, 1> z(in_z);
  EEM P(in_P);
  ZZM pre_R(in_R);

  // functions from sympy
  h_fun(in_x, in_ea, in_hx);
  H_fun(in_x, in_ea, in_H);
  ZDM pre_H(in_H);

  // get y (y = z - hx)
  Eigen::Matrix<double, ZDIM, 1> pre_y(in_hx); pre_y = z - pre_y;
  X1M y; XXM H; XXM R;
  if (Hea_fun){
    typedef Eigen::Matrix<double, ZDIM, EADIM, Eigen::RowMajor> ZAM;
    double in_Hea[ZDIM * EADIM] = {0};
    Hea_fun(in_x, in_ea, in_Hea);
    ZAM Hea(in_Hea);
    XXM A = Hea.transpose().fullPivLu().kernel();


    y = A.transpose() * pre_y;
    H = A.transpose() * pre_H;
    R = A.transpose() * pre_R * A;
  } else {
    y = pre_y;
    H = pre_H;
    R = pre_R;
  }
  // get modified H
  H_mod_fun(in_x, in_H_mod);
  DEM H_mod(in_H_mod);
  XEM H_err = H * H_mod;

  // Do mahalobis distance test
  if (MAHA_TEST){
    XXM a = (H_err * P * H_err.transpose() + R).inverse();
    double maha_dist = y.transpose() * a * y;
    if (maha_dist > MAHA_THRESHOLD){
      R = 1.0e16 * R;
    }
  }

  // Outlier resilient weighting
  double weight = 1;//(1.5)/(1 + y.squaredNorm()/R.sum());

  // kalman gains and I_KH
  XXM S = ((H_err * P) * H_err.transpose()) + R/weight;
  XEM KT = S.fullPivLu().solve(H_err * P.transpose());
  //EZM K = KT.transpose(); TODO: WHY DOES THIS NOT COMPILE?
  //EZM K = S.fullPivLu().solve(H_err * P.transpose()).transpose();
  //std::cout << "Here is the matrix rot:\n" << K << std::endl;
  EEM I_KH = Eigen::Matrix<double, EDIM, EDIM>::Identity() - (KT.transpose() * H_err);

  // update state by injecting dx
  Eigen::Matrix<double, EDIM, 1> dx(delta_x);
  dx  = (KT.transpose() * y);
  memcpy(delta_x, dx.data(), EDIM * sizeof(double));
  err_fun(in_x, delta_x, x_new);
  Eigen::Matrix<double, DIM, 1> x(x_new);

  // update cov
  P = ((I_KH * P) * I_KH.transpose()) + ((KT.transpose() * R) * KT);

  // copy out state
  memcpy(in_x, x.data(), DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
  memcpy(in_z, y.data(), y.rows() * sizeof(double));
}




}
extern "C" {

void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_25, H_25, NULL, in_z, in_R, in_ea, MAHA_THRESH_25);
}
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<2, 3, 0>(in_x, in_P, h_24, H_24, NULL, in_z, in_R, in_ea, MAHA_THRESH_24);
}
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_30, H_30, NULL, in_z, in_R, in_ea, MAHA_THRESH_30);
}
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_26, H_26, NULL, in_z, in_R, in_ea, MAHA_THRESH_26);
}
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_27, H_27, NULL, in_z, in_R, in_ea, MAHA_THRESH_27);
}
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_29, H_29, NULL, in_z, in_R, in_ea, MAHA_THRESH_29);
}
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_28, H_28, NULL, in_z, in_R, in_ea, MAHA_THRESH_28);
}
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_31, H_31, NULL, in_z, in_R, in_ea, MAHA_THRESH_31);
}
void car_err_fun(double *nom_x, double *delta_x, double *out_6375148504099374102) {
  err_fun(nom_x, delta_x, out_6375148504099374102);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_5936432944455214487) {
  inv_err_fun(nom_x, true_x, out_5936432944455214487);
}
void car_H_mod_fun(double *state, double *out_3687612785923554437) {
  H_mod_fun(state, out_3687612785923554437);
}
void car_f_fun(double *state, double dt, double *out_8923811346717442323) {
  f_fun(state,  dt, out_8923811346717442323);
}
void car_F_fun(double *state, double dt, double *out_1367243681225472950) {
  F_fun(state,  dt, out_1367243681225472950);
}
void car_h_25(double *state, double *unused, double *out_6503565297254880647) {
  h_25(state, unused, out_6503565297254880647);
}
void car_H_25(double *state, double *unused, double *out_164632135934062760) {
  H_25(state, unused, out_164632135934062760);
}
void car_h_24(double *state, double *unused, double *out_6019772980759252960) {
  h_24(state, unused, out_6019772980759252960);
}
void car_H_24(double *state, double *unused, double *out_6410939670657455341) {
  H_24(state, unused, out_6410939670657455341);
}
void car_h_30(double *state, double *unused, double *out_4411877301205886290) {
  h_30(state, unused, out_4411877301205886290);
}
void car_H_30(double *state, double *unused, double *out_6752058205557553995) {
  H_30(state, unused, out_6752058205557553995);
}
void car_h_26(double *state, double *unused, double *out_8051942933197523573) {
  h_26(state, unused, out_8051942933197523573);
}
void car_H_26(double *state, double *unused, double *out_3906135454808118984) {
  H_26(state, unused, out_3906135454808118984);
}
void car_h_27(double *state, double *unused, double *out_3466779245810547962) {
  h_27(state, unused, out_3466779245810547962);
}
void car_H_27(double *state, double *unused, double *out_4577294893757129084) {
  H_27(state, unused, out_4577294893757129084);
}
void car_h_29(double *state, double *unused, double *out_8392136901422708491) {
  h_29(state, unused, out_8392136901422708491);
}
void car_H_29(double *state, double *unused, double *out_2863932166887578051) {
  H_29(state, unused, out_2863932166887578051);
}
void car_h_28(double *state, double *unused, double *out_8468452513471393607) {
  h_28(state, unused, out_8468452513471393607);
}
void car_H_28(double *state, double *unused, double *out_2218466850181952523) {
  H_28(state, unused, out_2218466850181952523);
}
void car_h_31(double *state, double *unused, double *out_5172343550104320033) {
  h_31(state, unused, out_5172343550104320033);
}
void car_H_31(double *state, double *unused, double *out_133986174057102332) {
  H_31(state, unused, out_133986174057102332);
}
void car_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
void car_set_rotational_inertia(double x) {
  set_rotational_inertia(x);
}
void car_set_center_to_front(double x) {
  set_center_to_front(x);
}
void car_set_center_to_rear(double x) {
  set_center_to_rear(x);
}
void car_set_stiffness_front(double x) {
  set_stiffness_front(x);
}
void car_set_stiffness_rear(double x) {
  set_stiffness_rear(x);
}
}

const EKF car = {
  .name = "car",
  .kinds = { 25, 24, 30, 26, 27, 29, 28, 31 },
  .feature_kinds = {  },
  .f_fun = car_f_fun,
  .F_fun = car_F_fun,
  .err_fun = car_err_fun,
  .inv_err_fun = car_inv_err_fun,
  .H_mod_fun = car_H_mod_fun,
  .predict = car_predict,
  .hs = {
    { 25, car_h_25 },
    { 24, car_h_24 },
    { 30, car_h_30 },
    { 26, car_h_26 },
    { 27, car_h_27 },
    { 29, car_h_29 },
    { 28, car_h_28 },
    { 31, car_h_31 },
  },
  .Hs = {
    { 25, car_H_25 },
    { 24, car_H_24 },
    { 30, car_H_30 },
    { 26, car_H_26 },
    { 27, car_H_27 },
    { 29, car_H_29 },
    { 28, car_H_28 },
    { 31, car_H_31 },
  },
  .updates = {
    { 25, car_update_25 },
    { 24, car_update_24 },
    { 30, car_update_30 },
    { 26, car_update_26 },
    { 27, car_update_27 },
    { 29, car_update_29 },
    { 28, car_update_28 },
    { 31, car_update_31 },
  },
  .Hes = {
  },
  .sets = {
    { "rotational_inertia", car_set_rotational_inertia },
    { "center_to_front", car_set_center_to_front },
    { "center_to_rear", car_set_center_to_rear },
    { "stiffness_front", car_set_stiffness_front },
    { "stiffness_rear", car_set_stiffness_rear },
  },
  .extra_routines = {
  },
};

ekf_lib_init(car)
