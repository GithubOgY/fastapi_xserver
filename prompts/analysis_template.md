# AI Stock Analysis Prompt Template

You are a professional financial analyst. Please analyze the following company based on the provided financial data and qualitative information.

## Target Company
- **Ticker**: {{ ticker }}
- **Name**: {{ company_name }}

## Financial Data (Quantitative)
| Metrics | Current Period | Previous Period | YoY |
| :--- | :--- | :--- | :--- |
| Revenue | {{ revenue }} | {{ revenue_prev }} | {{ revenue_yoy }} |
| Operating Income | {{ op_income }} | {{ op_income_prev }} | {{ op_income_yoy }} |
| Net Income | {{ net_income }} | {{ net_income_prev }} | {{ net_income_yoy }} |
| Operating margin | {{ op_margin }} | - | - |
| EPS | {{ eps }} | - | - |
| ROE | {{ roe }} | - | - |

## Qualitative Information (from Annual Report)

### 1. Issues to be Addressed (対処すべき課題)
{{ issues_to_be_addressed }}

### 2. Business Risks (事業等のリスク)
{{ business_risks }}

### 3. Management Analysis (経営者による分析)
{{ management_analysis }}

## Instruction
Based on the above, please provide a comprehensive analysis in the following structure (in Japanese):

1.  **Executive Summary**: A concise 1-2 sentence overview of the company's current status (Bullish/Bearish/Neutral).
2.  **Performance Analysis**: Evaluation of the financial results. highlight keys factors driving growth or decline.
3.  **Risk Assessment**: Analyze the severity of the listed risks and how they might impact future earnings.
4.  **Future Outlook**: Based on the issues and management analysis, predict the future trajectory.
5.  **Conclusion**: Final investment verdict (Strong Buy / Buy / Hold / Sell).
