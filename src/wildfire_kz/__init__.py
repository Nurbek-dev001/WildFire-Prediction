"""wildfire_kz — explainable multisource next-day wildfire occurrence-hazard framework.

The framework estimates p_hat(i, t) = P(y(i, t) = 1 | x(i, <= t-1)): the probability that a
NEW vegetation-fire event is first detected by Suomi-NPP VIIRS in equal-area grid cell i on
UTC day t, using only information observed before day t. Outputs are occurrence hazard, not
damage, exposure or risk.
"""

__version__ = "0.1.0"
