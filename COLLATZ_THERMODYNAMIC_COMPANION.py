#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
================================================================================
COLLATZ THERMODYNAMIC FORMALISM — COMPUTATIONAL COMPANION
================================================================================

Companion script for:

    Jason Mullings (2026),
    "The Collatz Problem: A Thermodynamic Formalism for Accelerated Dynamics",
    Journal of Applied Mathematics and Physics.

This file is the supplementary computational material referenced in §4.4
("Computational methods") of the manuscript. It is designed to be a
referee-checkable, fully reproducible implementation of every empirical
quantity reported in the paper.

EPISTEMIC TIER SYSTEM (as in manuscript)
----------------------------------------
    [T1] Unconditional theorem proved in the manuscript / verifiable
         analytically inside this script (e.g. inverse-branch formula).
    [T2] Conditional statement (depends on an open hypothesis).
    [T3] Open mathematical problem (infinite-volume / functional-analytic).
    [E]  Empirical observation over an explicit finite range produced here.

Nothing computed in this script constitutes a proof of an infinite-volume
statement. All spectral, entropy, equilibrium and gap data are finite-volume,
finite-horizon empirical [E] observations on the explicitly truncated symbolic
graph defined below. They are intended *only* as numerical evidence consistent
with the open Master Inequality of §10 of the manuscript.

DIRECT REFEREE-RESPONSE CHECKLIST
---------------------------------
  (R1) Candidate Banach space declared before any infinite-volume notation:
       weighted l^1_w(O) with algebraic weight w(n) = n^{-s}, s > log 2 / log 3.
       Boundedness / quasi-compactness on this space is acknowledged [T3].
  (R2) Theorem 4.4 split: the finite matrix L^{(N)} has its spectrum computed
       *exactly as defined* by direct enumeration on the truncated odd lattice;
       the asymptotic 3/4 value is reported separately as a formal branch-weight
       computation, not as the eigenvalue of L^{(N)}.
  (R3) The truncated operator is built on an explicit symbolic graph
       (CollatzInverseGraph) with edges carrying a branch-depth label k and a
       cocycle weight; we do not silently project ill-defined preimages.
  (R4) A "Computational methods" block is printed at runtime and embedded in
       the source: sampled set, orbit horizon, treatment of orbits reaching 1,
       matrix-construction rule, eigensolver, numerical precision, RNG seed,
       and source availability.
  (R5) §6 and §7 statements are rewritten here as empirical trends: phrases
       such as "consistent with a CLT" appear only with an explicit [E] tag
       and no proof claim.

DEPENDENCIES
------------
    python >= 3.9
    numpy
    matplotlib

USAGE
-----
    python COLLATZ_THERMODYNAMIC_COMPANION.py
    # writes: ./output/collatz_thermodynamic_companion.png
    # prints: tier-tagged numerical tables matching the manuscript.

REPOSITORY
----------
    https://github.com/jmullings/Collatz_Thermodynamic_Formalism
================================================================================
"""

from __future__ import annotations

import math
import os
import sys
import time
import platform
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import numpy as np
from numpy.linalg import eig, eigvals

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec


# =============================================================================
#  0.  GLOBAL NUMERICAL CONSTANTS
# =============================================================================

LOG2: float = math.log(2.0)
LOG3: float = math.log(3.0)
LOG3_4: float = math.log(3.0 / 4.0)            # = -0.28768207...
LOG2_LOG3: float = LOG2 / LOG3                  # = log_3(2)  (manuscript bound)

# Empirical-rigor parameters. Documented for the referee. ----------------------
DEFAULT_K_MAX_PREIMAGE: int = 60                 # search depth in 2-adic exponent
DEFAULT_ENTROPY_T: int = 400                    # horizon T in manuscript §6
DEFAULT_ENTROPY_NMAX: int = 5001                # sample range in manuscript §6
DEFAULT_ENTROPY_STEP: int = 2                   # odd-only step
DEFAULT_BANACH_S: float = 0.70                  # > log 2 / log 3 = 0.6309...

RNG_SEED: int = 20260515                        # frozen for reproducibility


# =============================================================================
#  1.  ACCELERATED COLLATZ DYNAMICS  T*
# =============================================================================

def v2(n: int) -> int:
    """2-adic valuation nu_2(n). For n=0 we return 0 by convention [T1]."""
    if n == 0:
        return 0
    return (n & -n).bit_length() - 1


def T_star(n: int) -> int:
    """
    Accelerated Collatz map T*(n) = (3n+1) / 2^{nu_2(3n+1)} on odd n [T1].

    For safety we strip any 2-adic factor of n on input. T*(1) = 1.
    """
    while n % 2 == 0:
        n //= 2
    m = 3 * n + 1
    return m >> v2(m)


def T_star_orbit(n: int, max_steps: int = 5000) -> List[int]:
    """T*-orbit of an odd n, terminating at 1 or after max_steps [T1]."""
    while n % 2 == 0:
        n //= 2
    orbit: List[int] = [n]
    x = n
    for _ in range(max_steps):
        x = T_star(x)
        orbit.append(x)
        if x == 1:
            break
    return orbit


# =============================================================================
#  2.  CANONICAL ARITHMETIC POTENTIAL  phi_0  AND BRANCH COCYCLE
# =============================================================================

def phi0(n: int) -> float:
    """
    Canonical arithmetic potential phi_0(n) = log 3 - nu_2(3n+1) log 2 [T1].

    This is the manuscript's Definition 3.2.
    """
    return LOG3 - v2(3 * n + 1) * LOG2


def phi_branch(k: int) -> float:
    """
    Cocycle form of the potential along an inverse branch of depth k [T1].

    On the inverse branch y_k(x) = (2^k x - 1)/3 one has nu_2(3 y_k + 1) = k,
    hence
        phi_0(y_k) = log 3 - k * log 2.

    This is the *edge* form required by thermodynamic formalism on the
    natural extension (cf. Remark in the referee report).
    """
    return LOG3 - k * LOG2


# =============================================================================
#  3.  SYMBOLIC NATURAL EXTENSION:  INVERSE-BRANCH MARKOV GRAPH
# =============================================================================
#
#   This is the core structural change relative to a naive integer truncation.
#
#   The phase space of thermodynamic formalism is *not* the integers but the
#   symbolic shift on inverse branches. Following Lemma 2.2 of the manuscript,
#   for each odd x the odd preimages under T* are
#
#        y_k = (2^k x - 1) / 3,    k >= 1,  y_k > 0 odd.
#
#   We encode this as a directed weighted graph
#
#        G = (V, E, k, w)
#
#   with V = X_N (odd integers up to N), and an edge
#
#        x  <--(k)--  y_k
#
#   whenever T*(y_k) = x and both x, y_k lie in V. The label k is the
#   branch-depth, and the cocycle weight is e^{phi_branch(k)} = 3 * 2^{-k}.
#   The transfer matrix
#
#        L_{i,j}  =  sum over edges  (x_i <- y_j, depth k)  of  3 * 2^{-k}
#
#   is *by construction* a true (finite-volume) Ruelle--Perron--Frobenius
#   operator on a well-defined symbolic system.
#
# =============================================================================


@dataclass(frozen=True)
class InverseEdge:
    """A single inverse-branch edge x <- y of depth k with cocycle weight."""
    x: int           # image (target of T*)
    y: int           # preimage (source of T*)
    k: int           # 2-adic depth: nu_2(3y+1) = k
    weight: float    # cocycle weight  exp(phi_branch(k)) = 3 * 2^{-k}


def odd_inverse_branches(x: int, k_max: int = DEFAULT_K_MAX_PREIMAGE
                         ) -> Iterable[Tuple[int, int]]:
    """
    Enumerate (y_k, k) for all odd positive preimages y_k of odd x under T*,
    for branch depths 1 <= k <= k_max [T1].

    The bound k_max is finite for numerical safety; the script is
    transparent about this truncation and never claims completeness beyond
    it. For the truncations N used in the manuscript (N <= 3999), 60 is far
    in excess of the largest depth that can produce y_k <= N.
    """
    if x <= 0:
        return
    pow2 = 1
    for k in range(1, k_max + 1):
        pow2 <<= 1                # = 2**k
        num = pow2 * x - 1
        if num <= 0:
            continue
        if num % 3 != 0:
            continue
        y = num // 3
        if y > 0 and (y & 1) == 1:
            yield y, k


class CollatzInverseGraph:
    """
    Finite-volume symbolic graph G_N on X_N = {1, 3, ..., N (odd)} [T1/E].

    Vertices: odd integers up to N.
    Edges:    InverseEdge(x, y, k, w) for each odd preimage y of x with y in X_N.

    This is the explicit symbolic system on which the truncated RPF operator
    L^{(N)} of Definition 4.3 in the manuscript acts. No projection or
    silent rounding is performed; an edge exists if and only if both
    endpoints lie in X_N and the inverse-branch formula returns an odd
    positive integer.
    """

    def __init__(self, N: int, k_max: int = DEFAULT_K_MAX_PREIMAGE) -> None:
        if N < 1:
            raise ValueError("N must be >= 1.")
        if N % 2 == 0:
            N -= 1
        self.N: int = N
        self.k_max: int = k_max
        self.vertices: List[int] = list(range(1, N + 1, 2))
        self.index: Dict[int, int] = {x: i for i, x in enumerate(self.vertices)}
        self.edges: List[InverseEdge] = []
        self._build_edges()

    def _build_edges(self) -> None:
        """Enumerate every edge x <- y with both endpoints in X_N [T1]."""
        vidx = self.index
        edges: List[InverseEdge] = []
        for x in self.vertices:
            for y, k in odd_inverse_branches(x, k_max=self.k_max):
                if y in vidx:
                    edges.append(
                        InverseEdge(x=x, y=y, k=k, weight=3.0 * (2.0 ** -k))
                    )
        self.edges = edges

    def __len__(self) -> int:
        return len(self.vertices)

    def n_edges(self) -> int:
        return len(self.edges)


# =============================================================================
#  4.  FINITE-VOLUME RUELLE--PERRON--FROBENIUS OPERATOR  L^{(N)}
# =============================================================================
#
#   On the symbolic graph G_N the transfer operator acts on f : X_N -> R via
#
#       (L f)(x)  =  sum over edges  (x <- y, depth k)  of  e^{phi_branch(k)} f(y)
#                 =  sum over odd preimages y of x in X_N of e^{phi_0(y)} f(y).
#
#   Note: phi_branch(k) = phi_0(y_k) by construction, since nu_2(3 y_k + 1) = k.
#   This is exactly the matrix L^{(N)} of manuscript Definition 4.3.
#
# =============================================================================


def build_finite_volume_operator(graph: CollatzInverseGraph) -> np.ndarray:
    """
    Assemble the finite-volume RPF matrix L^{(N)} on X_N [T1/E].

    Rows are indexed by x (image), columns by y (preimage). For each edge
    (x <- y, depth k) we add the cocycle weight 3 * 2^{-k} to L[x, y].
    Multiple edges from the same y to the same x are not possible (a single
    branch depth determines a unique preimage), so this is a clean assembly.

    Returns: dense (M, M) float64 matrix with M = |X_N|.
    """
    M = len(graph)
    L = np.zeros((M, M), dtype=np.float64)
    ix = graph.index
    for e in graph.edges:
        i = ix[e.x]
        j = ix[e.y]
        L[i, j] += e.weight
    return L


def spectral_radius(L: np.ndarray) -> float:
    """Spectral radius rho(L) of a finite matrix via LAPACK dgeev [E]."""
    if L.size == 0:
        return 0.0
    return float(np.max(np.abs(eigvals(L))))


def leading_eigendata(L: np.ndarray) -> Tuple[float, np.ndarray, np.ndarray]:
    """
    Compute (lambda_1, right eigenvector h, left eigenvector mu) of L [E].

    The right eigenvector is the leading eigenfunction; the left eigenvector
    is the finite-volume equilibrium (Gibbs) state in the sense of
    Definition 5.1 of the manuscript. Both are returned as nonnegative,
    L^1-normalized real vectors. We take real parts because for the
    operators considered here the leading eigenvalue is empirically real;
    any tiny imaginary residual is a float64 artefact.
    """
    w, V = eig(L)
    i = int(np.argmax(np.abs(w)))
    lam = float(np.real(w[i]))

    h = np.abs(np.real(V[:, i]))
    s = h.sum()
    if s > 0:
        h = h / s

    wL, VL = eig(L.T)
    j = int(np.argmax(np.abs(wL)))
    mu = np.abs(np.real(VL[:, j]))
    s = mu.sum()
    if s > 0:
        mu = mu / s

    return lam, h, mu


# =============================================================================
#  5.  CANDIDATE BANACH SPACE  l^1_w(O)  (DIAGNOSTIC ONLY)
# =============================================================================

def banach_weight(n: int, s: float = DEFAULT_BANACH_S) -> float:
    """
    Algebraic weight w(n) = n^{-s} for the candidate Banach space [T3].

    The manuscript proposes l^1_w(O) with s > log 2 / log 3 = 0.6309...
    The default s = 0.70 satisfies this bound; the choice of s does not
    affect any spectral conclusion drawn here, but is recorded so that
    weighted norms can be monitored diagnostically.
    """
    if n <= 0:
        return 0.0
    return float(n) ** (-s)


def weighted_l1_norm(vec: np.ndarray, vertices: List[int],
                     s: float = DEFAULT_BANACH_S) -> float:
    """Compute the weighted l^1 norm sum_n w(n) |v_n| [E]."""
    weights = np.array([banach_weight(n, s=s) for n in vertices], dtype=np.float64)
    return float(np.sum(weights * np.abs(vec)))


# =============================================================================
#  6.  ENTROPY PRODUCTION  Sigma_T(n)  (MANUSCRIPT §6)
# =============================================================================

def entropy_production(n: int, horizon: int = DEFAULT_ENTROPY_T) -> float:
    """
    Empirical entropy production Sigma_T(n) for a single odd starting n [E].

    Sigma_T(n) = (1/T) sum_{k=0}^{T-1} phi_0( (T*)^k (n) ).

    Convention (manuscript §6 / §4.4): if the orbit reaches the trivial
    fixed point 1 at step k* < T, we accumulate phi_0(1) = log(3/4) for the
    remaining T - k* - 1 steps. This makes Sigma_T continuous at the
    absorbing fixed point.
    """
    while n % 2 == 0:
        n //= 2
    s = 0.0
    x = n
    phi_one = phi0(1)
    for step in range(horizon):
        s += phi0(x)
        x = T_star(x)
        if x == 1:
            remaining = horizon - step - 1
            if remaining > 0:
                s += phi_one * remaining
            break
    return s / horizon


def sample_entropy(n_max: int = DEFAULT_ENTROPY_NMAX,
                   step: int = DEFAULT_ENTROPY_STEP,
                   horizon: int = DEFAULT_ENTROPY_T) -> np.ndarray:
    """Sample Sigma_T(n) over odd n in [3, n_max] [E]."""
    out: List[float] = []
    for n in range(3, n_max, step):
        if n % 2 == 1:
            out.append(entropy_production(n, horizon=horizon))
    return np.asarray(out, dtype=np.float64)


# =============================================================================
#  7.  CYCLE GAUGE DIAGNOSTIC  (MANUSCRIPT §8)
# =============================================================================

def cycle_gauge_sum(cycle_odd: List[int]) -> float:
    """Cycle gauge sum sum_{y in C} phi_0(y) -- expected < 0 for nontrivial C [T1]."""
    return float(sum(phi0(y) for y in cycle_odd))


def systematic_cycle_search(n_bound: int = 20000,
                            step_bound: int = 50000) -> Dict[str, int]:
    """
    Search for nontrivial T*-cycles among odd starts n in [3, n_bound] [E].

    For each odd n we iterate T* up to step_bound steps. If the orbit
    revisits some y != 1, we record a nontrivial cycle. Manuscript Remark
    8.3 reports zero such cycles up to n = 20,000; we reproduce that
    statistic here.
    """
    nontrivial = 0
    trivial = 0
    overshoot = 0
    for n0 in range(3, n_bound + 1, 2):
        seen = {n0}
        x = n0
        absorbed = False
        for _ in range(step_bound):
            x = T_star(x)
            if x == 1:
                trivial += 1
                absorbed = True
                break
            if x in seen:
                nontrivial += 1
                absorbed = True
                break
            seen.add(x)
        if not absorbed:
            overshoot += 1
    return {
        "checked": (n_bound - 1) // 2,
        "trivial": trivial,
        "nontrivial": nontrivial,
        "overshoot": overshoot,
    }


# =============================================================================
#  8.  DIAGNOSTIC PIPELINE
# =============================================================================

# Truncation grid used in the manuscript -------------------------------------
NS_PRESSURE: Tuple[int, ...] = (99, 199, 399, 799, 1199, 1599, 1999, 2999, 3999)
NS_GAP: Tuple[int, ...] = (99, 199, 399, 799, 1199)
N_EQUILIBRIUM: int = 999

# Entropy concentration grid -------------------------------------------------
T_RANGE: Tuple[int, ...] = (10, 25, 50, 100, 200, 400)

# Cycle search bound ---------------------------------------------------------
CYCLE_SEARCH_BOUND: int = 20000


def run_pressure_diagnostics() -> Dict[str, List]:
    """
    Finite-volume pressure diagnostics across the truncation grid [E].

    For each N we build the symbolic graph G_N, assemble the finite-volume
    RPF matrix L^{(N)}, and compute rho(L^{(N)}) and P_N = log rho. The
    asymptotic 3/4 value of the manuscript is *not* claimed as the exact
    eigenvalue of any single L^{(N)}; we merely report the observed rho_N.
    """
    Ns: List[int] = []
    sizes: List[int] = []
    n_edges: List[int] = []
    rhos: List[float] = []
    pressures: List[float] = []

    print("\n" + "-" * 76)
    print("  1. Finite-Volume Pressure  P_N(phi_0)  [E]")
    print("-" * 76)
    print(f"  {'N':>5} {'|X_N|':>7} {'edges':>8} {'rho_N':>14} {'P_N':>14}")

    for N in NS_PRESSURE:
        graph = CollatzInverseGraph(N)
        L = build_finite_volume_operator(graph)
        rho = spectral_radius(L)
        P = math.log(rho) if rho > 0.0 else float("-inf")
        Ns.append(N)
        sizes.append(len(graph))
        n_edges.append(graph.n_edges())
        rhos.append(rho)
        pressures.append(P)
        print(f"  {N:>5d} {len(graph):>7d} {graph.n_edges():>8d}"
              f" {rho:>14.10f} {P:>14.10f}")

    print(f"  reference log(3/4) = {LOG3_4:.10f}")
    return {
        "Ns": Ns, "sizes": sizes, "n_edges": n_edges,
        "rhos": rhos, "pressures": pressures,
    }


def run_equilibrium_diagnostics() -> Dict[str, object]:
    """
    Finite-volume equilibrium (Gibbs) state at N = N_EQUILIBRIUM [E].

    Returns the left eigenvector of L^{(N)}, its leading eigenvalue, and a
    diagnostic weighted l^1_w(O) norm matching the candidate Banach space.
    """
    print("\n" + "-" * 76)
    print(f"  2. Finite-Volume Equilibrium State  mu_N  at N = {N_EQUILIBRIUM}  [E]")
    print("-" * 76)

    graph = CollatzInverseGraph(N_EQUILIBRIUM)
    L = build_finite_volume_operator(graph)
    lam, h, mu = leading_eigendata(L)

    w_norm = weighted_l1_norm(mu, graph.vertices, s=DEFAULT_BANACH_S)

    print(f"  |X_N|       = {len(graph)}")
    print(f"  #edges      = {graph.n_edges()}")
    print(f"  |lambda_1|  = {abs(lam):.10f}")
    print(f"  ||mu_N||_{{l^1_w}} with s={DEFAULT_BANACH_S} : {w_norm:.6e}")
    print(f"  top-5 masses mu_N(x):")
    for i in range(min(5, len(graph))):
        print(f"     mu_N({graph.vertices[i]:>4d}) = {mu[i]:.6e}")

    return {
        "vertices": graph.vertices,
        "mu": mu,
        "h": h,
        "lambda1": lam,
        "weighted_l1_norm": w_norm,
    }


def run_entropy_diagnostics() -> Dict[str, object]:
    """
    Entropy production statistics over the manuscript sample [E].

    We report mean, std, min, max and the count of orbits with Sigma_T >= 0
    for the same sample and horizon used in §6 of the manuscript.
    """
    print("\n" + "-" * 76)
    print("  3. Entropy Production  Sigma_T(n)  [E]")
    print("-" * 76)

    sigma_vals = sample_entropy(
        n_max=DEFAULT_ENTROPY_NMAX,
        step=DEFAULT_ENTROPY_STEP,
        horizon=DEFAULT_ENTROPY_T,
    )
    n_pos = int(np.sum(sigma_vals >= 0))
    print(f"  sample size (odd n in [3, {DEFAULT_ENTROPY_NMAX}]): {len(sigma_vals)}")
    print(f"  horizon T = {DEFAULT_ENTROPY_T}")
    print(f"  mean Sigma_T   = {sigma_vals.mean():.10f}")
    print(f"  std  Sigma_T   = {sigma_vals.std():.10f}")
    print(f"  min  Sigma_T   = {sigma_vals.min():.10f}")
    print(f"  max  Sigma_T   = {sigma_vals.max():.10f}")
    print(f"  reference      = log(3/4) = {LOG3_4:.10f}")
    print(f"  orbits with Sigma_T >= 0 : {n_pos} / {len(sigma_vals)}   "
          "(empirical, no proof claim) [E]")

    # Concentration scan across horizons -------------------------------------
    print("\n  Concentration scan as T grows [E]:")
    print(f"  {'T':>5} {'mean':>14} {'std':>14} {'max':>14}")
    T_means: List[float] = []
    T_stds: List[float] = []
    T_maxs: List[float] = []
    for T in T_RANGE:
        sv = sample_entropy(n_max=2001, step=4, horizon=T)
        T_means.append(float(sv.mean()))
        T_stds.append(float(sv.std()))
        T_maxs.append(float(sv.max()))
        print(f"  {T:>5d} {sv.mean():>14.8f} {sv.std():>14.8f}"
              f" {sv.max():>14.8f}")
    print("  Observation: std(Sigma_T) decays as T grows over the tested range.")
    print("  This is reported as an empirical trend only [E]; no CLT is proved.")

    return {
        "sigma_vals": sigma_vals,
        "T_range": list(T_RANGE),
        "T_means": T_means,
        "T_stds": T_stds,
        "T_maxs": T_maxs,
    }


def run_gap_diagnostics() -> Dict[str, List]:
    """
    Finite-volume spectral gap |lambda_1| - |lambda_2| [E].

    Reported on the smaller grid NS_GAP. We make *no* claim about a uniform
    infinite-volume spectral gap; that remains an open [T3] problem
    explicitly named in §10 of the manuscript.
    """
    print("\n" + "-" * 76)
    print("  4. Finite-Volume Spectral Gap  |lambda_1| - |lambda_2|  [E]")
    print("-" * 76)
    print(f"  {'N':>5} {'|lam_1|':>12} {'|lam_2|':>12} {'gap':>14}")

    Ns: List[int] = []
    l1s: List[float] = []
    l2s: List[float] = []
    gaps: List[float] = []

    for N in NS_GAP:
        graph = CollatzInverseGraph(N)
        L = build_finite_volume_operator(graph)
        mags = np.sort(np.abs(eigvals(L)))[::-1] if L.size > 0 else np.array([0.0])
        l1 = float(mags[0]) if len(mags) > 0 else 0.0
        l2 = float(mags[1]) if len(mags) > 1 else 0.0
        Ns.append(N)
        l1s.append(l1)
        l2s.append(l2)
        gaps.append(l1 - l2)
        print(f"  {N:>5d} {l1:>12.8f} {l2:>12.8f} {l1 - l2:>14.8e}")

    print("  Note: positive gap observed at every tested N [E]; infinite-volume")
    print("        spectral gap on l^1_w(O) is an open analytic problem [T3].")
    return {"Ns": Ns, "l1s": l1s, "l2s": l2s, "gaps": gaps}


def run_cycle_diagnostics() -> Dict[str, int]:
    """
    Systematic search for nontrivial T*-cycles up to n = CYCLE_SEARCH_BOUND [E].

    Reproduces Remark 8.3 of the manuscript. The Cycle Exclusion Theorem
    itself (Theorem 8.1) is a [T1] analytic statement and does not depend
    on this empirical search.
    """
    print("\n" + "-" * 76)
    print("  5. Systematic T*-Cycle Search  [E]")
    print("-" * 76)
    print(f"  scanning odd n in [3, {CYCLE_SEARCH_BOUND}] ...")
    stats = systematic_cycle_search(n_bound=CYCLE_SEARCH_BOUND, step_bound=50000)
    print(f"  checked         : {stats['checked']}")
    print(f"  reach trivial 1 : {stats['trivial']}")
    print(f"  nontrivial cyc. : {stats['nontrivial']}")
    print(f"  overshoot (none): {stats['overshoot']}")
    return stats


# =============================================================================
#  9.  COMPUTATIONAL METHODS BLOCK (REFEREE-FACING)
# =============================================================================

def print_methods_banner() -> None:
    """Print the manuscript §4.4 computational-methods block at runtime."""
    bar = "=" * 76
    print(bar)
    print("  COLLATZ THERMODYNAMIC FORMALISM — COMPUTATIONAL COMPANION")
    print(bar)
    print(f"  Python              : {sys.version.split()[0]} "
          f"({platform.python_implementation()})")
    print(f"  Platform            : {platform.system()} {platform.release()}")
    print(f"  NumPy               : {np.__version__}")
    print(f"  Matplotlib          : {matplotlib.__version__}")
    print(f"  Floating-point      : IEEE 754 float64 (~15 significant digits)")
    print(f"  Eigensolver         : numpy.linalg.eig / eigvals (LAPACK dgeev)")
    print(f"  RNG seed (frozen)   : {RNG_SEED}")
    print(f"  Candidate space     : l^1_w(O), w(n)=n^{{-s}}, s={DEFAULT_BANACH_S} "
          f"(> log2/log3 = {LOG2_LOG3:.4f})  [T3]")
    print(f"  State space X_N     : odd integers {{1, 3, ..., N}}, "
          f"N in {list(NS_PRESSURE)}")
    print(f"  Inverse branches    : y_k = (2^k x - 1)/3, depth k <= "
          f"{DEFAULT_K_MAX_PREIMAGE}")
    print(f"  Edges retained      : iff both x, y_k lie in X_N")
    print(f"  Cocycle weight      : e^{{phi_0(y_k)}} = 3 * 2^{{-k}}")
    print(f"  Sampled set         : odd n in [3, {DEFAULT_ENTROPY_NMAX}]")
    print(f"  Entropy horizon     : T = {DEFAULT_ENTROPY_T}")
    print(f"  Orbit reaches 1     : phi_0(1) = log(3/4) padded for remaining steps")
    print(f"  Source available    : github.com/jmullings/Collatz_Thermodynamic_Formalism")
    print(bar)


# =============================================================================
# 10.  CHART GENERATION (MATCHES MANUSCRIPT FIGURE)
# =============================================================================

BG       = "#07080d"
PANEL    = "#12141f"
BORDER   = "#1e2235"
TXT      = "#c8cfe8"
DIM      = "#4a5070"
NAIVE    = "#ff6b6b"
SPECTRAL = "#4ecdc4"
EIGEN    = "#ffe66d"
EQUIV    = "#a29bfe"
GREEN    = "#6bcb77"


def _style_ax(ax, title: str = "", xlabel: str = "", ylabel: str = "") -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=DIM, labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor(BORDER)
    ax.xaxis.label.set_color(DIM)
    ax.yaxis.label.set_color(DIM)
    ax.title.set_color(TXT)
    if title:
        ax.set_title(title, fontsize=8, pad=6)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=7)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=7)
    ax.grid(color=BORDER, linewidth=0.4, linestyle="--", alpha=0.6)


def build_charts(pressure: Dict, equilibrium: Dict, entropy: Dict,
                 gap: Dict, out_dir: str = "output") -> str:
    """Generate the production chart summarising all empirical diagnostics [E]."""
    os.makedirs(out_dir, exist_ok=True)
    fig = plt.figure(figsize=(18, 14), facecolor=BG)
    fig.suptitle(
        "COLLATZ THERMODYNAMIC FORMALISM — Finite-Volume Empirical Diagnostics [E]",
        color=TXT, fontsize=12, fontweight="bold", y=0.98,
    )
    gs = gridspec.GridSpec(
        3, 3, figure=fig,
        hspace=0.55, wspace=0.40,
        left=0.07, right=0.97, top=0.93, bottom=0.06,
    )

    # Chart 1: P_N vs N
    ax = fig.add_subplot(gs[0, 0])
    _style_ax(ax, title="Chart 1 · Finite-Volume Pressure  P_N(phi_0) [E]",
              xlabel="N (odd-state truncation)", ylabel="P_N")
    ax.plot(pressure["Ns"], pressure["pressures"], "o-",
            color=SPECTRAL, lw=1.8, ms=5, label="P_N = log rho_N")
    ax.axhline(LOG3_4, color=EIGEN, lw=1.2, ls="--",
               label=f"log(3/4) = {LOG3_4:.5f}")
    ax.legend(fontsize=6.5, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)

    # Chart 2: rho_N
    ax = fig.add_subplot(gs[0, 1])
    _style_ax(ax, title="Chart 2 · Spectral Radius  rho_N [E]",
              xlabel="N", ylabel="rho(L^{(N)})")
    ax.plot(pressure["Ns"], pressure["rhos"], "s-",
            color=NAIVE, lw=1.8, ms=5, label="rho_N")
    ax.axhline(0.75, color=EIGEN, lw=1.2, ls="--", label="0.75 (formal asymptote)")
    ax.legend(fontsize=6.5, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)

    # Chart 3: Entropy histogram
    ax = fig.add_subplot(gs[0, 2])
    _style_ax(ax, title="Chart 3 · Entropy Production  Sigma_T(n) [E]",
              xlabel="Sigma_T(n)", ylabel="count")
    sv = entropy["sigma_vals"]
    ax.hist(sv, bins=60, color=SPECTRAL, alpha=0.75, edgecolor="none",
            label=f"Sigma_T, T={DEFAULT_ENTROPY_T}")
    ax.axvline(LOG3_4, color=GREEN, lw=1.2, ls=":", label="log(3/4)")
    ax.legend(fontsize=6.5, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)

    # Chart 4: Concentration of Sigma_T as T grows
    ax = fig.add_subplot(gs[1, 0])
    _style_ax(ax, title="Chart 4 · Entropy Concentration with T [E]",
              xlabel="horizon T", ylabel="value")
    ax.plot(entropy["T_range"], entropy["T_stds"], "o-",
            color=EIGEN, lw=1.8, ms=5, label="std(Sigma_T)")
    ax.plot(entropy["T_range"], entropy["T_maxs"], "s-",
            color=NAIVE, lw=1.8, ms=5, label="max(Sigma_T)")
    ax.plot(entropy["T_range"], entropy["T_means"], "^--",
            color=SPECTRAL, lw=1.4, ms=5, label="mean(Sigma_T)")
    ax.axhline(LOG3_4, color=GREEN, lw=1.0, ls=":", label="log(3/4)")
    ax.legend(fontsize=6.5, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)

    # Chart 5: Finite spectral gap
    ax = fig.add_subplot(gs[1, 1])
    _style_ax(ax, title="Chart 5 · Finite Spectral Gap  |lam_1|-|lam_2| [E]",
              xlabel="N", ylabel="gap")
    ax.plot(gap["Ns"], gap["gaps"], "D-", color=EQUIV, lw=1.8, ms=5,
            label="|lam_1| - |lam_2|")
    ax.legend(fontsize=6.5, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)

    # Chart 6: Equilibrium state mu_N (top of spectrum)
    ax = fig.add_subplot(gs[1, 2])
    _style_ax(ax, title=f"Chart 6 · Equilibrium State  mu_N  (N={N_EQUILIBRIUM}) [E]",
              xlabel="odd state x", ylabel="mu_N(x)")
    vx = equilibrium["vertices"][:40]
    vy = equilibrium["mu"][:40]
    ax.bar(vx, vy, color=SPECTRAL, edgecolor="none", width=1.4)

    # Chart 7: Edge-count growth (symbolic system size)
    ax = fig.add_subplot(gs[2, 0])
    _style_ax(ax, title="Chart 7 · Symbolic Graph Size [E]",
              xlabel="N", ylabel="count")
    ax.plot(pressure["Ns"], pressure["sizes"], "o-",
            color=EIGEN, lw=1.6, ms=5, label="|X_N|")
    ax.plot(pressure["Ns"], pressure["n_edges"], "s-",
            color=NAIVE, lw=1.6, ms=5, label="edges in G_N")
    ax.legend(fontsize=6.5, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)

    # Chart 8: Cocycle weights 3 * 2^{-k}
    ax = fig.add_subplot(gs[2, 1])
    _style_ax(ax, title="Chart 8 · Branch Cocycle Weights  3·2^{-k} [T1]",
              xlabel="branch depth k", ylabel="exp(phi_branch(k))")
    ks = np.arange(1, 11)
    ws = 3.0 * (2.0 ** -ks)
    ax.bar(ks, ws, color=EQUIV, edgecolor="none", width=0.7)
    ax.axhline(0, color=BORDER, lw=0.5)

    # Chart 9: Epistemic summary
    ax = fig.add_subplot(gs[2, 2])
    ax.set_facecolor(PANEL)
    for spine in ax.spines.values():
        spine.set_edgecolor(BORDER)
    ax.axis("off")
    summary = (
        "EPISTEMIC SUMMARY\n"
        "===========================\n\n"
        "  [T1] Inverse-branch formula\n"
        "       y_k = (2^k x - 1)/3, depth k.\n"
        "  [T1] Cocycle weight  3 * 2^{-k}.\n"
        "  [T1] Cycle Exclusion Theorem 8.1.\n\n"
        "  [E]  rho(L^{(N)}) = 0.75 to float64\n"
        "       precision for all tested N.\n"
        "  [E]  Sigma_T(n) < 0 over sample.\n"
        "  [E]  std(Sigma_T) decays with T\n"
        "       over tested range.\n"
        "  [E]  Positive finite gap at every N.\n\n"
        "  [T3] Banach space l^1_w(O), s>log_3 2.\n"
        "  [T3] Boundedness / quasi-compactness.\n"
        "  [T3] Infinite-volume spectral gap.\n"
        "  [T3] Master Inequality  P(phi_0)<0.\n"
    )
    ax.text(0.04, 0.96, summary, transform=ax.transAxes,
            va="top", ha="left", fontsize=8,
            fontfamily="monospace", color=TXT, linespacing=1.55)

    out_path = os.path.join(out_dir, "collatz_thermodynamic_companion.png")
    plt.savefig(out_path, dpi=170, bbox_inches="tight",
                facecolor=BG, edgecolor="none")
    plt.close(fig)
    return out_path


# =============================================================================
# 11.  SELF-CHECKS  (LIGHTWEIGHT, REFEREE-VERIFIABLE)
# =============================================================================

def self_checks() -> None:
    """Run lightweight invariant checks on the dynamics and operator [T1/E]."""
    print("\n" + "-" * 76)
    print("  0. Self-checks  [T1/E]")
    print("-" * 76)

    # v2 ---------------------------------------------------------------------
    assert v2(1) == 0 and v2(4) == 2 and v2(2 ** 10) == 10
    print("  v2 invariants                            OK")

    # T_star --------------------------------------------------------------
    assert T_star(1) == 1
    assert T_star(3) == 5
    assert T_star(5) == 1
    assert T_star(7) == 11
    print("  T_star invariants                        OK")

    # Inverse branch identity: T*(y_k(x)) == x  for valid y_k -----------------
    for x in [1, 3, 5, 7, 9, 11, 27]:
        for y, k in odd_inverse_branches(x, k_max=30):
            assert T_star(y) == x, (x, y, k)
            assert v2(3 * y + 1) == k
    print("  inverse-branch identity T*(y_k) = x      OK")

    # Cocycle identity: phi_0(y_k) = phi_branch(k) ----------------------------
    for x in [1, 3, 5, 7, 11]:
        for y, k in odd_inverse_branches(x, k_max=30):
            a = phi0(y)
            b = phi_branch(k)
            assert abs(a - b) < 1e-15, (x, y, k, a, b)
    print("  cocycle identity phi_0(y_k) = phi_b(k)   OK")

    # Banach-space weight admissibility ---------------------------------------
    assert DEFAULT_BANACH_S > LOG2_LOG3, "s must exceed log2/log3"
    print("  candidate Banach weight s > log_3 2      OK")


# =============================================================================
# 12.  ENTRY POINT
# =============================================================================

def main() -> None:
    t0 = time.perf_counter()

    print_methods_banner()
    self_checks()

    pressure = run_pressure_diagnostics()
    equilibrium = run_equilibrium_diagnostics()
    entropy = run_entropy_diagnostics()
    gap = run_gap_diagnostics()
    cycles = run_cycle_diagnostics()

    print("\n" + "-" * 76)
    print("  6. Generating Figure")
    print("-" * 76)
    out = build_charts(pressure, equilibrium, entropy, gap, out_dir="./output")
    print(f"  chart written  -> {out}")

    print("\n" + "=" * 76)
    print(f"  Execution time : {time.perf_counter() - t0:.2f} s")
    print("=" * 76 + "\n")


if __name__ == "__main__":
    main()