"""
Selectors
"""
from typing import List, Optional, Union, Dict, Callable

import numpy as np
from scipy.optimize import minimize, NonlinearConstraint
from scipy.linalg import lstsq
from sklearn.metrics import get_scorer
from sklearn.linear_model import LinearRegression


class BaseSelector:
    """
    Feature selector. This is meant to work on relatively smaller
    number of features
    """
    def __init__(self, coef_thres: float = 1e-6, method: str = 'SLSQP'):
        """
        Base selector
        Args:
            coef_thres (float): threshold to discard certain coefficents
            method (str): optimization methods in scipy.optmize.minimize
        """
        self.coef_thres = coef_thres
        self.is_fitted = False
        self.coef_ = None
        self.method = method

    def select(self, x, y, options=None) -> List[int]:
        """
        Select feature indices from x

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets
            options (dict): options in the optimizations provided
                to scipy.optimize.minimize
        Returns: list of int indices
        """

        n_data, n_dim = x.shape
        options = options or {"maxiter": 1e4, 'ftol': 1e-12}
        res = minimize(lambda beta: self.construct_loss(x=x, y=y, beta=beta), [0] * n_dim,
                       jac=self.construct_jac(x=x, y=y),
                       method=self.method,
                       constraints=self.construct_constraints(x=x, y=y), options=options)
        if res.status != 0:
            raise RuntimeError(f"Not converged, status {res.status}")
        self.is_fitted = True
        self.coef_ = res.x
        # output coefficient indices that are above certain thresholds
        return np.where(np.abs(self.coef_) > self.coef_thres)[0]

    def construct_loss(self, x: np.ndarray, y: np.ndarray, beta: np.ndarray) -> float:
        """
        Get loss function from data and tentative coefficients beta

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets
            beta (np.ndarray): N coefficients

        Returns: loss value

        """
        raise NotImplementedError

    def construct_constraints(self, x: np.ndarray, y: np.ndarray) \
            -> Optional[Union[Dict, List[Dict], NonlinearConstraint]]:
        """
        Get constraints dictionary from data, e.g.,
        {"func": lambda beta: fun(x, y, beta), "type": "ineq"}

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets

        Returns: dict of constraints

        """
        return None

    def construct_jac(self, x: np.ndarray, y: np.ndarray) -> Optional[Callable]:
        """
        Jacobian of cost function
        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets

        Returns: Jacobian function

        """
        return None

    def evaluate(self, x: np.ndarray, y: np.ndarray,
                 metric: str = 'neg_mean_absolute_error') -> float:
        """
        Evaluate the linear model using x, and y test data

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets
            metric (str): scorer function, used with
                sklearn.metrics.get_scorer

        Returns:

        """
        metric_func = get_scorer(metric)
        lr = LinearRegression(fit_intercept=False)
        lr.coef_ = self.coef_
        lr.intercept_ = 0
        return metric_func(lr, x, y)

    def get_coef(self) -> np.ndarray:
        """
        Get coefficients
        Returns: the coefficients array

        """
        return self.coef_


class DantzigSelector(BaseSelector):
    """
    Equation 11 in
    https://orfe.princeton.edu/~jqfan/papers/06/SIS.pdf
    and reference in https://projecteuclid.org/download/pdfview_1/euclid.aos/1201012958
    """
    def __init__(self, lambd, sigma=1.0, **kwargs):
        """
        Dantzig selector

        Args:
            lamb: tunable parameter
            sigma: standard deviation of the error
        """
        self.lambd = lambd
        self.sigma = sigma
        super().__init__(**kwargs)

    def construct_loss(self, x, y, beta) -> float:
        """
        Get loss function from data and tentative coefficients beta

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets
            beta (np.ndarray): N coefficients

        Returns: loss value

        """
        return np.sum(np.abs(beta)).item()

    def construct_jac(self, x: np.ndarray, y: np.ndarray) -> Callable:
        """
        Jacobian of cost functions
        Args:
            x: 
            y: 

        Returns:

        """
        def _jac(beta):
            sign = np.sign(beta)
            sign[np.abs(sign) < 0.1] = 1.
            sign *= 30.0  # multiply the gradients to get better convergence
            return sign
        return _jac

    def construct_constraints(self, x, y) -> NonlinearConstraint:
        """
        Get constraints dictionary from data, e.g.,
        {"func": lambda beta: fun(x, y, beta), "type": "ineq"}

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets

        Returns: dict of constraints

        """
        def _constraint(beta):
            return np.linalg.norm(x.T @ (y - x @ beta), np.infty)

        def _jac(beta):
            vec = x.T @ (y - x @ beta)
            max_ind = np.argmax(np.abs(vec))
            der = np.zeros_like(vec.ravel())
            der[max_ind] = np.sign(vec[max_ind])
            return -x.T.dot(x).dot(der)

        return NonlinearConstraint(_constraint, -np.infty, self.lambd * self.sigma,
                                   jac=_jac)


class PenalizedLeastSquares(BaseSelector):
    """
    Penalized least squares. In addition to minimizing the sum of squares loss,
    it adds an additional penalty to the coefficients
    """
    def construct_loss(self, x: np.ndarray, y: np.ndarray,
                       beta: np.ndarray) -> float:
        """
        Construct the loss function. An extra penalty term is added

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets
            beta (np.ndarray): N coefficients

        Returns: sum of errors

        """
        n = x.shape[0]
        se = 1. / (2 * n) * np.sum((y - x.dot(beta))**2) + \
            self.penalty(beta, x=x, y=y)
        return se

    def _sse_jac(self, x, y, beta):
        n = x.shape[0]
        return 1. / n * (y - x.dot(beta)).T.dot(-x)

    def _penalty_jac(self, x, y, beta):
        return 0.0

    def construct_jac(self, x: np.ndarray, y: np.ndarray):
        """
        Construct the jacobian of loss function
        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets

        Returns: jacobian vector

        """
        def _jac(beta):
            return self._sse_jac(x, y, beta) + self._penalty_jac(x, y, beta)
        return _jac

    def construct_constraints(self, x: np.ndarray, y: np.ndarray) \
            -> List[Optional[Dict]]:
        """
        No constraints

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets

        Returns: a list of dictionary constraints

        """
        return []

    def penalty(self, beta: np.ndarray, x: Optional[np.ndarray] = None,
                y: Optional[np.ndarray] = None) -> float:
        """
        Calculate the penalty from input x, output y and coefficient beta

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets
            beta (np.ndarray): N coefficients

        Returns: penalty value

        """
        return 0.


class SCAD(PenalizedLeastSquares):
    """
    Smoothly clipped absolute deviation (SCAD),
    equation 12 and 13 in https://orfe.princeton.edu/~jqfan/papers/06/SIS.pdf
    """

    def __init__(self, lambd: Union[float, np.ndarray],
                 a: float = 3.7, **kwargs):
        """
        Smoothly clipped absolute deviation.

        Args:
            lambd (float or list of floats): The weights for the penalty
            a (float): hyperparameter in SCAD penalty
        """
        self.lambd = lambd
        self.a = a
        super().__init__(**kwargs)

    def penalty(self, beta: np.ndarray, x: Optional[np.ndarray] = None,
                y: Optional[np.ndarray] = None) -> float:
        """
        Calculate the SCAD penalty from input x, output y
            and coefficient beta

        Args:
            beta (np.ndarray): N coefficients
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets

        Returns: penalty value

        """
        beta_abs = np.abs(beta)
        penalty = self.lambd * beta_abs * (beta_abs <= self.lambd) + \
            - (beta_abs**2 - 2 * self.a * self.lambd * beta_abs + self.lambd ** 2) / (2 * (self.a - 1)) * \
            (beta_abs > self.lambd) * (beta_abs <= self.a * self.lambd) + \
            (self.a + 1) * self.lambd ** 2 / 2.0 * (beta_abs > self.a * self.lambd)
        return np.sum(penalty).item()

    def _penalty_jac(self, x, y, beta):
        beta = np.abs(beta)
        x = self.a * self.lambd - beta
        x[x < 0] = 0
        return self.lambd * (beta <= self.lambd +
                             x / ((self.a - 1) * self.lambd) * (beta > self.lambd))


class Lasso(PenalizedLeastSquares):
    """
    Simple Lasso regression
    """

    def __init__(self, lambd, **kwargs):
        """
        Lasso regression with lambda * norm_1(beta) as penalty
        Args:
            lambd (float): weights for the penalty
            **kwargs:
        """
        self.lambd = lambd
        super().__init__(**kwargs)

    def penalty(self, beta: np.ndarray, x: Optional[np.ndarray] = None,
                y: Optional[np.ndarray] = None) -> float:
        """
        Calculate the penalty from input x, output y and coefficient beta

        Args:
            beta (np.ndarray): N coefficients
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets

        Returns: penalty value

        """
        beta_abs = np.abs(beta)
        return np.sum(self.lambd * beta_abs).item()

    def _penalty_jac(self, x, y, beta):
        sign = np.sign(beta)
        sign[np.abs(sign) < 0.2] = 1
        return self.lambd * sign


class AdaptiveLasso(PenalizedLeastSquares):
    """
    Adaptive lasso regression using OLS coefficients
    as the root-n estimator coefficients
    """
    def __init__(self, lambd, gamma, **kwargs):
        """
        Adaptive lasso regression

        Args:
            lambd (float or list of floats):
            gamma (float): exponential for hat(beta)
            **kwargs:
        """
        self.lambd = lambd
        self.gamma = gamma
        self.w = 1
        super().__init__(**kwargs)

    def select(self, x, y, options=None) -> List[int]:
        """
        Select feature indices from x

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets
            options (dict): options in the optimizations provided
                to scipy.optimize.minimize
        Returns: list of int indices
        """
        self.w = self.get_w(x, y)
        return super().select(x, y, options)

    def get_w(self, x, y) -> np.ndarray:
        """
        Get adaptive weights from data

        Args:
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets

        Returns: coefficients array

        """
        beta_hat = lstsq(x, y)[0]
        w = 1. / np.abs(beta_hat) ** self.gamma
        return w

    def penalty(self, beta: np.ndarray, x: Optional[np.ndarray] = None,
                y: Optional[np.ndarray] = None) -> float:
        """
        Calculate the penalty from input x, output y and coefficient beta

        Args:
            beta (np.ndarray): N coefficients
            x (np.ndarray): MxN input data array
            y (np.ndarray): M output targets

        Returns: penalty value

        """
        return np.sum(self.lambd * self.w * np.abs(beta)).item()

    def _penalty_jac(self, x, y, beta):
        sign = np.sign(beta)
        sign[np.abs(sign) < 0.2] = 1
        return self.lambd * self.w * sign