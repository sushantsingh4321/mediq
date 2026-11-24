"""
Queuing theory maths for mediQ.

We model each OPD department as an M/M/c queue:
  M  -> patients ARRIVE randomly (a Poisson process) at an average rate  lambda (per hour)
  M  -> each consultation takes a random time (exponential), average 1/mu  hours
  c  -> number of doctors working in parallel in that department

Read LEARN.md, Part 1, for a plain-language explanation of every formula here.
This file has no FastAPI code in it on purpose: it is pure maths, so it is easy
to test and easy to reuse later (e.g. in a city-wide module).
"""

from math import factorial


def mmc_metrics(arrival_rate: float, service_rate: float, servers: int) -> dict:
    """
    Classic M/M/c results.

    arrival_rate  (lambda): patients arriving per hour
    service_rate  (mu):     patients ONE doctor can see per hour
    servers       (c):      number of doctors

    Returns a dict with:
      utilization  (rho) - how busy the doctors are, 0..1 (1 = 100% busy)
      prob_wait          - chance a new patient has to wait at all (Erlang C)
      avg_queue_length   - Lq, average number of people waiting (not being seen)
      avg_wait_minutes   - Wq, average time spent waiting before seeing a doctor
      avg_time_in_system_minutes - W, waiting + consultation
      stable             - False if patients arrive faster than doctors can see them
    """
    if servers < 1 or service_rate <= 0:
        raise ValueError("Need at least 1 doctor and a positive service rate")

    lam, mu, c = arrival_rate, service_rate, servers
    rho = lam / (c * mu)  # utilization

    if lam <= 0:
        # Nobody arriving: nobody waits.
        return {
            "utilization": 0.0, "prob_wait": 0.0, "avg_queue_length": 0.0,
            "avg_wait_minutes": 0.0, "avg_time_in_system_minutes": 60 / mu,
            "stable": True,
        }

    if rho >= 1:
        # Arrivals >= capacity: the queue grows forever. Formulas break down.
        return {
            "utilization": rho, "prob_wait": 1.0, "avg_queue_length": None,
            "avg_wait_minutes": None, "avg_time_in_system_minutes": None,
            "stable": False,
        }

    a = lam / mu  # "offered load": how many doctors' worth of work arrives
    # Erlang C formula: probability that an arriving patient must wait.
    top = (a ** c / factorial(c)) * (1 / (1 - rho))
    bottom = sum(a ** k / factorial(k) for k in range(c)) + top
    prob_wait = top / bottom

    wq_hours = prob_wait / (c * mu - lam)   # average wait in queue
    lq = lam * wq_hours                     # Little's Law: L = lambda * W
    w_hours = wq_hours + 1 / mu             # wait + consultation

    return {
        "utilization": round(rho, 4),
        "prob_wait": round(prob_wait, 4),
        "avg_queue_length": round(lq, 2),
        "avg_wait_minutes": round(wq_hours * 60, 1),
        "avg_time_in_system_minutes": round(w_hours * 60, 1),
        "stable": True,
    }


def estimate_wait_for_position(people_ahead: int, servers: int, avg_consult_minutes: float) -> float:
    """
    Simple, practical estimate for ONE specific patient:
    "There are N people ahead of you and c doctors, each taking ~T minutes,
     so you wait roughly (N / c) * T minutes."

    This is what a token display shows. The M/M/c numbers above describe the
    department on AVERAGE over a day; this one describes the queue RIGHT NOW.
    """
    if servers < 1:
        raise ValueError("Need at least 1 doctor")
    return round((people_ahead / servers) * avg_consult_minutes, 1)
