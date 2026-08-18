import numpy as np


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def r2(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ss_res = float(np.sum((a - b) ** 2))
    ss_tot = float(np.sum((a - a.mean()) ** 2))
    return 1 - ss_res / ss_tot


def evaluate(y_true, pred):
    exp_t = np.exp(np.asarray(y_true, dtype=float))
    exp_p = np.exp(np.asarray(pred, dtype=float))
    return {
        "rmse": round(rmse(y_true, pred), 4),
        "mae": round(mae(y_true, pred), 4),
        "r2": round(r2(y_true, pred), 4),
        "rmse_dollars": round(rmse(exp_t, exp_p), 3),
        "mae_dollars": round(mae(exp_t, exp_p), 3),
    }
