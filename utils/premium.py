"""
Premium Plan Management Utilities

This module handles premium tier access control and feature gating.
"""

from datetime import datetime, timezone
from typing import Optional
from database import User


class PremiumTier:
    """Premium tier definitions"""
    FREE = "free"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class PremiumFeatures:
    """Premium feature definitions and limits"""

    # Free tier limits
    FREE_AI_ANALYSES_PER_DAY = 3
    FREE_FAVORITE_LIMIT = 5
    FREE_COMPARISON_LIMIT = 2

    # Premium tier limits
    PREMIUM_AI_ANALYSES_PER_DAY = 50
    PREMIUM_FAVORITE_LIMIT = 100
    PREMIUM_COMPARISON_LIMIT = 10

    # Enterprise tier limits (unlimited)
    ENTERPRISE_AI_ANALYSES_PER_DAY = 999999
    ENTERPRISE_FAVORITE_LIMIT = 999999
    ENTERPRISE_COMPARISON_LIMIT = 999999

    # Feature access by tier
    FEATURES = {
        "ai_analysis": {
            PremiumTier.FREE: True,
            PremiumTier.PREMIUM: True,
            PremiumTier.ENTERPRISE: True,
        },
        "advanced_charts": {
            PremiumTier.FREE: False,
            PremiumTier.PREMIUM: True,
            PremiumTier.ENTERPRISE: True,
        },
        "export_data": {
            PremiumTier.FREE: False,
            PremiumTier.PREMIUM: True,
            PremiumTier.ENTERPRISE: True,
        },
        "api_access": {
            PremiumTier.FREE: False,
            PremiumTier.PREMIUM: False,
            PremiumTier.ENTERPRISE: True,
        },
        "priority_support": {
            PremiumTier.FREE: False,
            PremiumTier.PREMIUM: True,
            PremiumTier.ENTERPRISE: True,
        },
        "no_ads": {
            PremiumTier.FREE: False,
            PremiumTier.PREMIUM: True,
            PremiumTier.ENTERPRISE: True,
        },
    }


def is_premium_active(user: User) -> bool:
    """
    Check if user has an active premium subscription.

    Args:
        user: User object from database

    Returns:
        bool: True if premium is active, False otherwise
    """
    if not user:
        return False

    # Admins always have premium access
    if user.is_admin:
        return True

    # Check if user is on free tier
    if user.premium_tier == PremiumTier.FREE:
        return False

    # Check if premium has expired
    if user.premium_until:
        now = datetime.now(timezone.utc)
        if now > user.premium_until:
            return False

    return True


def get_user_tier(user: Optional[User]) -> str:
    """
    Get the effective tier for a user.

    Args:
        user: User object from database (or None for anonymous)

    Returns:
        str: Premium tier (free, premium, or enterprise)
    """
    if not user:
        return PremiumTier.FREE

    # Admins get enterprise tier
    if user.is_admin:
        return PremiumTier.ENTERPRISE

    # Check if premium is active
    if is_premium_active(user):
        return user.premium_tier

    return PremiumTier.FREE


def has_feature_access(user: Optional[User], feature: str) -> bool:
    """
    Check if user has access to a specific feature.

    Args:
        user: User object from database (or None for anonymous)
        feature: Feature name (see PremiumFeatures.FEATURES)

    Returns:
        bool: True if user has access, False otherwise
    """
    tier = get_user_tier(user)
    feature_map = PremiumFeatures.FEATURES.get(feature, {})
    return feature_map.get(tier, False)


def get_feature_limit(user: Optional[User], feature: str) -> int:
    """
    Get the limit for a feature based on user's tier.

    Args:
        user: User object from database (or None for anonymous)
        feature: Feature name (ai_analyses, favorites, comparisons)

    Returns:
        int: Feature limit
    """
    tier = get_user_tier(user)

    limits = {
        "ai_analyses": {
            PremiumTier.FREE: PremiumFeatures.FREE_AI_ANALYSES_PER_DAY,
            PremiumTier.PREMIUM: PremiumFeatures.PREMIUM_AI_ANALYSES_PER_DAY,
            PremiumTier.ENTERPRISE: PremiumFeatures.ENTERPRISE_AI_ANALYSES_PER_DAY,
        },
        "favorites": {
            PremiumTier.FREE: PremiumFeatures.FREE_FAVORITE_LIMIT,
            PremiumTier.PREMIUM: PremiumFeatures.PREMIUM_FAVORITE_LIMIT,
            PremiumTier.ENTERPRISE: PremiumFeatures.ENTERPRISE_FAVORITE_LIMIT,
        },
        "comparisons": {
            PremiumTier.FREE: PremiumFeatures.FREE_COMPARISON_LIMIT,
            PremiumTier.PREMIUM: PremiumFeatures.PREMIUM_COMPARISON_LIMIT,
            PremiumTier.ENTERPRISE: PremiumFeatures.ENTERPRISE_COMPARISON_LIMIT,
        },
    }

    return limits.get(feature, {}).get(tier, 0)


def get_tier_display_name(tier: str) -> str:
    """
    Get display name for a tier.

    Args:
        tier: Tier code (free, premium, enterprise)

    Returns:
        str: Display name
    """
    names = {
        PremiumTier.FREE: "無料プラン",
        PremiumTier.PREMIUM: "プレミアムプラン",
        PremiumTier.ENTERPRISE: "エンタープライズプラン",
    }
    return names.get(tier, "無料プラン")


def get_tier_badge_html(tier: str) -> str:
    """
    Get HTML badge for a tier.

    Args:
        tier: Tier code (free, premium, enterprise)

    Returns:
        str: HTML badge
    """
    badges = {
        PremiumTier.FREE: '<span style="background: #64748b; color: white; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600;">FREE</span>',
        PremiumTier.PREMIUM: '<span style="background: linear-gradient(135deg, #f59e0b, #d97706); color: white; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600;">⭐ PREMIUM</span>',
        PremiumTier.ENTERPRISE: '<span style="background: linear-gradient(135deg, #8b5cf6, #6d28d9); color: white; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600;">💎 ENTERPRISE</span>',
    }
    return badges.get(tier, badges[PremiumTier.FREE])
