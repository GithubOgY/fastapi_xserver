"""
Chart.js Data Formatting Utilities

This module formats technical analysis data for Chart.js visualization.
"""

import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime


def format_chartjs_data(df: pd.DataFrame, indicators: Dict[str, pd.Series]) -> Dict:
    """
    Format stock data and technical indicators for Chart.js

    Args:
        df: DataFrame with stock data (must have DatetimeIndex and OHLCV columns)
        indicators: Dict of calculated technical indicators

    Returns:
        Dict in Chart.js format with labels and datasets
    """
    # Convert datetime index to string labels
    labels = [date.strftime('%Y-%m-%d') for date in df.index]

    # Price data (candlestick will be handled separately, using Close for line chart)
    price_data = df['Close'].tolist()

    # Prepare datasets
    datasets = []

    # 1. Price Line (Close)
    datasets.append({
        'label': '株価',
        'data': price_data,
        'borderColor': 'rgba(59, 130, 246, 1)',
        'backgroundColor': 'rgba(59, 130, 246, 0.1)',
        'borderWidth': 2,
        'pointRadius': 0,
        'pointHoverRadius': 4,
        'yAxisID': 'y-price',
        'order': 1
    })

    # 2. 25-day Moving Average
    if 'ma' in indicators:
        ma_data = indicators['ma'].tolist()
        datasets.append({
            'label': '移動平均線(25日)',
            'data': ma_data,
            'borderColor': 'rgba(251, 146, 60, 1)',
            'backgroundColor': 'transparent',
            'borderWidth': 2,
            'pointRadius': 0,
            'borderDash': [5, 5],
            'yAxisID': 'y-price',
            'order': 2
        })

    # 3. Bollinger Bands
    if all(k in indicators for k in ['bb_upper', 'bb_middle', 'bb_lower']):
        # Upper Band
        datasets.append({
            'label': 'ボリンジャーバンド上限',
            'data': indicators['bb_upper'].tolist(),
            'borderColor': 'rgba(168, 85, 247, 0.5)',
            'backgroundColor': 'transparent',
            'borderWidth': 1,
            'pointRadius': 0,
            'borderDash': [3, 3],
            'yAxisID': 'y-price',
            'order': 3
        })

        # Middle Band
        datasets.append({
            'label': 'ボリンジャーバンド中央',
            'data': indicators['bb_middle'].tolist(),
            'borderColor': 'rgba(168, 85, 247, 0.3)',
            'backgroundColor': 'transparent',
            'borderWidth': 1,
            'pointRadius': 0,
            'borderDash': [1, 1],
            'yAxisID': 'y-price',
            'order': 4
        })

        # Lower Band
        datasets.append({
            'label': 'ボリンジャーバンド下限',
            'data': indicators['bb_lower'].tolist(),
            'borderColor': 'rgba(168, 85, 247, 0.5)',
            'backgroundColor': 'transparent',
            'borderWidth': 1,
            'pointRadius': 0,
            'borderDash': [3, 3],
            'yAxisID': 'y-price',
            'order': 5
        })

    # 4. Ichimoku Cloud Components
    if all(k in indicators for k in ['ichimoku_tenkan', 'ichimoku_kijun', 'ichimoku_senkou_a', 'ichimoku_senkou_b']):
        # Tenkan-sen (Conversion Line)
        datasets.append({
            'label': '転換線',
            'data': indicators['ichimoku_tenkan'].tolist(),
            'borderColor': 'rgba(239, 68, 68, 0.8)',
            'backgroundColor': 'transparent',
            'borderWidth': 1.5,
            'pointRadius': 0,
            'yAxisID': 'y-price',
            'order': 6
        })

        # Kijun-sen (Base Line)
        datasets.append({
            'label': '基準線',
            'data': indicators['ichimoku_kijun'].tolist(),
            'borderColor': 'rgba(34, 197, 94, 0.8)',
            'backgroundColor': 'transparent',
            'borderWidth': 1.5,
            'pointRadius': 0,
            'yAxisID': 'y-price',
            'order': 7
        })

        # Senkou Span A (Leading Span A) - Cloud
        senkou_a_data = indicators['ichimoku_senkou_a'].tolist()
        senkou_b_data = indicators['ichimoku_senkou_b'].tolist()

        datasets.append({
            'label': '先行スパンA',
            'data': senkou_a_data,
            'borderColor': 'rgba(34, 197, 94, 0.3)',
            'backgroundColor': 'rgba(34, 197, 94, 0.1)',
            'borderWidth': 1,
            'pointRadius': 0,
            'fill': '+1',  # Fill to next dataset (Senkou Span B)
            'yAxisID': 'y-price',
            'order': 8
        })

        # Senkou Span B (Leading Span B) - Cloud
        datasets.append({
            'label': '先行スパンB',
            'data': senkou_b_data,
            'borderColor': 'rgba(239, 68, 68, 0.3)',
            'backgroundColor': 'rgba(239, 68, 68, 0.1)',
            'borderWidth': 1,
            'pointRadius': 0,
            'yAxisID': 'y-price',
            'order': 9
        })

    # 5. RSI (separate Y-axis)
    if 'rsi' in indicators:
        rsi_data = indicators['rsi'].tolist()
        datasets.append({
            'label': 'RSI',
            'data': rsi_data,
            'borderColor': 'rgba(147, 51, 234, 1)',
            'backgroundColor': 'rgba(147, 51, 234, 0.1)',
            'borderWidth': 2,
            'pointRadius': 0,
            'pointHoverRadius': 4,
            'yAxisID': 'y-rsi',
            'order': 10
        })

    return {
        'labels': labels,
        'datasets': datasets
    }


def get_chart_config(period: str = '3M') -> Dict:
    """
    Get Chart.js configuration object

    Args:
        period: Time period for the chart (1M, 3M, 6M, 1Y)

    Returns:
        Chart.js configuration dict
    """
    return {
        'type': 'line',
        'options': {
            'responsive': True,
            'maintainAspectRatio': False,
            'interaction': {
                'mode': 'index',
                'intersect': False
            },
            'plugins': {
                'legend': {
                    'display': True,
                    'position': 'top',
                    'labels': {
                        'usePointStyle': True,
                        'padding': 15,
                        'font': {
                            'size': 11
                        }
                    }
                },
                'tooltip': {
                    'enabled': True,
                    'mode': 'index',
                    'intersect': False
                },
                'zoom': {
                    'zoom': {
                        'wheel': {
                            'enabled': True
                        },
                        'pinch': {
                            'enabled': True
                        },
                        'mode': 'x'
                    },
                    'pan': {
                        'enabled': True,
                        'mode': 'x'
                    }
                }
            },
            'scales': {
                'x': {
                    'display': True,
                    'title': {
                        'display': True,
                        'text': '日付'
                    },
                    'ticks': {
                        'maxTicksLimit': 10,
                        'maxRotation': 45,
                        'minRotation': 0
                    }
                },
                'y-price': {
                    'type': 'linear',
                    'display': True,
                    'position': 'left',
                    'title': {
                        'display': True,
                        'text': '株価 (円)'
                    },
                    'grid': {
                        'drawOnChartArea': True
                    }
                },
                'y-rsi': {
                    'type': 'linear',
                    'display': True,
                    'position': 'right',
                    'title': {
                        'display': True,
                        'text': 'RSI'
                    },
                    'min': 0,
                    'max': 100,
                    'grid': {
                        'drawOnChartArea': False
                    },
                    'ticks': {
                        'callback': 'function(value) { return value; }'
                    }
                }
            }
        }
    }


def calculate_period_days(period: str) -> int:
    """
    Convert period string to number of days

    Args:
        period: Period string (1M, 3M, 6M, 1Y)

    Returns:
        Number of days
    """
    period_map = {
        '1M': 30,
        '3M': 90,
        '6M': 180,
        '1Y': 365
    }
    return period_map.get(period, 90)  # Default to 3 months
