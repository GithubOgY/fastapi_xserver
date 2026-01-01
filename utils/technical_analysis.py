"""
Technical Analysis Indicators

This module calculates various technical indicators for stock analysis.
Designed for use with yfinance DataFrame data.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


def calculate_moving_average(df: pd.DataFrame, period: int = 25, column: str = 'Close') -> pd.Series:
    """
    Calculate Simple Moving Average (SMA)

    Args:
        df: DataFrame with stock data
        period: Number of periods for MA (default: 25)
        column: Column name to calculate MA from (default: 'Close')

    Returns:
        pd.Series: Moving average values
    """
    return df[column].rolling(window=period).mean()


def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0, column: str = 'Close') -> Dict[str, pd.Series]:
    """
    Calculate Bollinger Bands

    Args:
        df: DataFrame with stock data
        period: Number of periods for MA (default: 20)
        std_dev: Number of standard deviations (default: 2.0)
        column: Column name to calculate from (default: 'Close')

    Returns:
        Dict with 'middle', 'upper', 'lower' bands
    """
    middle_band = df[column].rolling(window=period).mean()
    std = df[column].rolling(window=period).std()

    upper_band = middle_band + (std * std_dev)
    lower_band = middle_band - (std * std_dev)

    return {
        'middle': middle_band,
        'upper': upper_band,
        'lower': lower_band
    }


def calculate_rsi(df: pd.DataFrame, period: int = 14, column: str = 'Close') -> pd.Series:
    """
    Calculate Relative Strength Index (RSI)

    Args:
        df: DataFrame with stock data
        period: Number of periods for RSI (default: 14)
        column: Column name to calculate from (default: 'Close')

    Returns:
        pd.Series: RSI values (0-100)
    """
    delta = df[column].diff()

    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_ichimoku(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """
    Calculate Ichimoku Cloud (一目均衡表) components

    Args:
        df: DataFrame with stock data (must have 'High', 'Low', 'Close')

    Returns:
        Dict with Ichimoku components:
        - tenkan_sen: Conversion Line (転換線) - 9 period
        - kijun_sen: Base Line (基準線) - 26 period
        - senkou_span_a: Leading Span A (先行スパンA) - shifted +26
        - senkou_span_b: Leading Span B (先行スパンB) - shifted +26
        - chikou_span: Lagging Span (遅行スパン) - shifted -26
    """
    high = df['High']
    low = df['Low']
    close = df['Close']

    # Tenkan-sen (Conversion Line): (9-period high + 9-period low)/2
    period9_high = high.rolling(window=9).max()
    period9_low = low.rolling(window=9).min()
    tenkan_sen = (period9_high + period9_low) / 2

    # Kijun-sen (Base Line): (26-period high + 26-period low)/2
    period26_high = high.rolling(window=26).max()
    period26_low = low.rolling(window=26).min()
    kijun_sen = (period26_high + period26_low) / 2

    # Senkou Span A (Leading Span A): (Conversion Line + Base Line)/2
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(26)

    # Senkou Span B (Leading Span B): (52-period high + 52-period low)/2
    period52_high = high.rolling(window=52).max()
    period52_low = low.rolling(window=52).min()
    senkou_span_b = ((period52_high + period52_low) / 2).shift(26)

    # Chikou Span (Lagging Span): Current closing price shifted back 26 periods
    chikou_span = close.shift(-26)

    return {
        'tenkan_sen': tenkan_sen,
        'kijun_sen': kijun_sen,
        'senkou_span_a': senkou_span_a,
        'senkou_span_b': senkou_span_b,
        'chikou_span': chikou_span
    }


def calculate_all_indicators(df: pd.DataFrame,
                             ma_period: int = 25,
                             bb_period: int = 20,
                             rsi_period: int = 14) -> Dict[str, any]:
    """
    Calculate all technical indicators at once

    Args:
        df: DataFrame with stock data (must have OHLCV columns)
        ma_period: Period for moving average (default: 25)
        bb_period: Period for Bollinger Bands (default: 20)
        rsi_period: Period for RSI (default: 14)

    Returns:
        Dict containing all indicators
    """
    indicators = {}

    # Moving Average
    indicators['ma'] = calculate_moving_average(df, period=ma_period)

    # Bollinger Bands
    bb = calculate_bollinger_bands(df, period=bb_period)
    indicators['bb_upper'] = bb['upper']
    indicators['bb_middle'] = bb['middle']
    indicators['bb_lower'] = bb['lower']

    # RSI
    indicators['rsi'] = calculate_rsi(df, period=rsi_period)

    # Ichimoku Cloud
    ichimoku = calculate_ichimoku(df)
    indicators['ichimoku_tenkan'] = ichimoku['tenkan_sen']
    indicators['ichimoku_kijun'] = ichimoku['kijun_sen']
    indicators['ichimoku_senkou_a'] = ichimoku['senkou_span_a']
    indicators['ichimoku_senkou_b'] = ichimoku['senkou_span_b']
    indicators['ichimoku_chikou'] = ichimoku['chikou_span']

    return indicators


def get_latest_values(indicators: Dict[str, pd.Series]) -> Dict[str, Optional[float]]:
    """
    Get the latest (most recent) value from each indicator

    Args:
        indicators: Dict of indicator Series

    Returns:
        Dict with latest values (None if not available)
    """
    latest = {}
    for name, series in indicators.items():
        try:
            latest[name] = float(series.iloc[-1]) if pd.notna(series.iloc[-1]) else None
        except (IndexError, TypeError):
            latest[name] = None

    return latest
