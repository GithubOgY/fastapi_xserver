"""
日本語メッセージ定義ファイル
Japanese Locale Messages for Xserver Stock Analysis Application

このファイルは、アプリケーション全体で使用される日本語メッセージを管理します。
UIテキスト、エラーメッセージ、ヘルプテキストなどを一元管理します。
"""

from typing import Dict, Any


class Messages:
    """日本語メッセージクラス"""

    # ========================================
    # 共通メッセージ
    # ========================================
    COMMON = {
        "app_name": "Xserver株式分析",
        "welcome": "ようこそ",
        "loading": "読み込み中...",
        "saving": "保存中...",
        "processing": "処理中...",
        "success": "成功しました",
        "error": "エラーが発生しました",
        "warning": "警告",
        "info": "情報",
        "confirm": "確認",
        "cancel": "キャンセル",
        "ok": "OK",
        "yes": "はい",
        "no": "いいえ",
        "save": "保存",
        "delete": "削除",
        "edit": "編集",
        "close": "閉じる",
        "back": "戻る",
        "next": "次へ",
        "previous": "前へ",
        "search": "検索",
        "filter": "フィルター",
        "sort": "並び替え",
        "refresh": "更新",
        "export": "エクスポート",
        "import": "インポート",
        "download": "ダウンロード",
        "upload": "アップロード",
        "required": "必須",
        "optional": "任意",
        "all": "すべて",
        "none": "なし",
        "select": "選択",
        "selected": "選択済み",
        "clear": "クリア",
        "reset": "リセット",
        "submit": "送信",
        "apply": "適用",
        "view": "表示",
        "hide": "非表示",
        "show_more": "もっと見る",
        "show_less": "閉じる",
    }

    # ========================================
    # 認証・ログイン関連
    # ========================================
    AUTH = {
        "login": "ログイン",
        "logout": "ログアウト",
        "register": "新規登録",
        "username": "ユーザー名",
        "email": "メールアドレス",
        "password": "パスワード",
        "password_confirm": "パスワード（確認）",
        "remember_me": "ログイン状態を保持",
        "forgot_password": "パスワードをお忘れですか？",
        "reset_password": "パスワードをリセット",
        "change_password": "パスワードを変更",
        "current_password": "現在のパスワード",
        "new_password": "新しいパスワード",
        "login_success": "ログインしました",
        "logout_success": "ログアウトしました",
        "register_success": "アカウントを作成しました",
        "password_reset_sent": "パスワードリセットメールを送信しました",
        "password_changed": "パスワードを変更しました",
        "login_required": "ログインが必要です",
        "invalid_credentials": "ユーザー名またはパスワードが正しくありません",
        "email_already_exists": "このメールアドレスは既に登録されています",
        "username_already_exists": "このユーザー名は既に使用されています",
        "weak_password": "パスワードが弱すぎます",
        "password_mismatch": "パスワードが一致しません",
        "unauthorized": "認証が必要です",
        "forbidden": "アクセス権限がありません",
        "session_expired": "セッションが期限切れです。再度ログインしてください",
    }

    # ========================================
    # ナビゲーション
    # ========================================
    NAV = {
        "home": "ホーム",
        "dashboard": "ダッシュボード",
        "search": "銘柄検索",
        "favorites": "お気に入り",
        "portfolio": "ポートフォリオ",
        "analysis": "分析",
        "news": "ニュース",
        "settings": "設定",
        "profile": "プロフィール",
        "help": "ヘルプ",
        "about": "このアプリについて",
        "admin": "管理画面",
    }

    # ========================================
    # 企業・銘柄情報
    # ========================================
    COMPANY = {
        "company": "企業",
        "company_name": "企業名",
        "company_code": "証券コード",
        "ticker": "ティッカー",
        "sector": "業種",
        "industry": "産業",
        "market": "市場",
        "scale_category": "規模区分",
        "description": "企業概要",
        "website": "Webサイト",
        "headquarters": "本社所在地",
        "founded": "設立年",
        "employees": "従業員数",
        "ceo": "代表取締役",
        "fiscal_year_end": "決算月",
        "listing_date": "上場日",
        "search_placeholder": "企業名またはコードで検索",
        "no_results": "該当する企業が見つかりません",
        "loading_companies": "企業情報を読み込んでいます...",
    }

    # ========================================
    # 財務情報
    # ========================================
    FINANCIAL = {
        "financial_data": "財務データ",
        "financial_statement": "財務諸表",
        "income_statement": "損益計算書",
        "balance_sheet": "貸借対照表",
        "cash_flow": "キャッシュフロー計算書",
        "revenue": "売上高",
        "operating_income": "営業利益",
        "ordinary_income": "経常利益",
        "net_income": "当期純利益",
        "total_assets": "総資産",
        "total_liabilities": "総負債",
        "equity": "純資産",
        "operating_cash_flow": "営業キャッシュフロー",
        "investing_cash_flow": "投資キャッシュフロー",
        "financing_cash_flow": "財務キャッシュフロー",
        "eps": "1株当たり利益（EPS）",
        "bps": "1株当たり純資産（BPS）",
        "roe": "自己資本利益率（ROE）",
        "roa": "総資産利益率（ROA）",
        "per": "株価収益率（PER）",
        "pbr": "株価純資産倍率（PBR）",
        "dividend": "配当金",
        "dividend_yield": "配当利回り",
        "payout_ratio": "配当性向",
        "fiscal_year": "会計年度",
        "quarter": "四半期",
        "annual": "年次",
        "growth_rate": "成長率",
        "year_over_year": "前年同期比",
        "margin": "利益率",
        "gross_margin": "売上総利益率",
        "operating_margin": "営業利益率",
        "net_margin": "純利益率",
    }

    # ========================================
    # 株価情報
    # ========================================
    STOCK = {
        "stock_price": "株価",
        "current_price": "現在値",
        "opening_price": "始値",
        "high_price": "高値",
        "low_price": "安値",
        "closing_price": "終値",
        "previous_close": "前日終値",
        "change": "変動",
        "change_percent": "変動率",
        "volume": "出来高",
        "market_cap": "時価総額",
        "52_week_high": "52週高値",
        "52_week_low": "52週安値",
        "average_volume": "平均出来高",
        "chart": "チャート",
        "candlestick": "ローソク足",
        "line_chart": "折れ線グラフ",
        "time_range": "期間",
        "1_day": "1日",
        "1_week": "1週間",
        "1_month": "1ヶ月",
        "3_months": "3ヶ月",
        "6_months": "6ヶ月",
        "1_year": "1年",
        "5_years": "5年",
        "max": "最大",
        "up": "上昇",
        "down": "下落",
        "unchanged": "変わらず",
    }

    # ========================================
    # AI分析
    # ========================================
    AI_ANALYSIS = {
        "ai_analysis": "AI分析",
        "analyze": "分析する",
        "analyzing": "分析中...",
        "analysis_result": "分析結果",
        "financial_health": "財務健全性分析",
        "business_competitiveness": "事業競争力分析",
        "risk_governance": "リスク・ガバナンス分析",
        "growth_quality": "成長性・質の分析",
        "comprehensive_analysis": "総合分析",
        "ai_insights": "AIインサイト",
        "strengths": "強み",
        "weaknesses": "弱み",
        "opportunities": "機会",
        "threats": "脅威",
        "recommendation": "推奨",
        "investment_rating": "投資評価",
        "buy": "買い",
        "hold": "保有",
        "sell": "売り",
        "analysis_failed": "分析に失敗しました",
        "analysis_completed": "分析が完了しました",
        "cached_result": "キャッシュされた分析結果",
        "refresh_analysis": "分析を更新",
        "analysis_date": "分析日時",
    }

    # ========================================
    # ユーザー機能
    # ========================================
    USER = {
        "profile": "プロフィール",
        "my_page": "マイページ",
        "account_settings": "アカウント設定",
        "display_name": "表示名",
        "bio": "自己紹介",
        "avatar": "アバター",
        "joined_date": "登録日",
        "last_login": "最終ログイン",
        "email_verified": "メール認証済み",
        "verify_email": "メールアドレスを認証",
        "update_profile": "プロフィールを更新",
        "profile_updated": "プロフィールを更新しました",
        "delete_account": "アカウントを削除",
        "delete_account_confirm": "本当にアカウントを削除しますか？この操作は取り消せません。",
    }

    # ========================================
    # お気に入り
    # ========================================
    FAVORITES = {
        "favorites": "お気に入り",
        "add_to_favorites": "お気に入りに追加",
        "remove_from_favorites": "お気に入りから削除",
        "favorite_added": "お気に入りに追加しました",
        "favorite_removed": "お気に入りから削除しました",
        "no_favorites": "お気に入りの銘柄がありません",
        "manage_favorites": "お気に入りを管理",
    }

    # ========================================
    # コメント・ディスカッション
    # ========================================
    COMMENTS = {
        "comments": "コメント",
        "comment": "コメント",
        "discussion": "ディスカッション",
        "post_comment": "コメントを投稿",
        "edit_comment": "コメントを編集",
        "delete_comment": "コメントを削除",
        "comment_posted": "コメントを投稿しました",
        "comment_updated": "コメントを更新しました",
        "comment_deleted": "コメントを削除しました",
        "reply": "返信",
        "replies": "返信",
        "no_comments": "まだコメントがありません",
        "write_comment": "コメントを書く...",
        "comment_placeholder": "この銘柄についてのあなたの意見を共有してください",
        "delete_comment_confirm": "このコメントを削除しますか？",
    }

    # ========================================
    # フォロー機能
    # ========================================
    SOCIAL = {
        "follow": "フォロー",
        "unfollow": "フォロー解除",
        "following": "フォロー中",
        "followers": "フォロワー",
        "followed": "フォローしました",
        "unfollowed": "フォローを解除しました",
        "no_followers": "まだフォロワーがいません",
        "no_following": "まだ誰もフォローしていません",
    }

    # ========================================
    # 通知
    # ========================================
    NOTIFICATIONS = {
        "notifications": "通知",
        "notification_settings": "通知設定",
        "email_notifications": "メール通知",
        "price_alerts": "株価アラート",
        "news_alerts": "ニュースアラート",
        "comment_notifications": "コメント通知",
        "follow_notifications": "フォロー通知",
        "mark_as_read": "既読にする",
        "mark_all_as_read": "すべて既読にする",
        "no_notifications": "新しい通知はありません",
    }

    # ========================================
    # エラーメッセージ
    # ========================================
    ERRORS = {
        "error": "エラー",
        "error_occurred": "エラーが発生しました",
        "not_found": "ページが見つかりません",
        "server_error": "サーバーエラーが発生しました",
        "network_error": "ネットワークエラー",
        "invalid_input": "入力内容が正しくありません",
        "required_field": "この項目は必須です",
        "invalid_email": "メールアドレスの形式が正しくありません",
        "invalid_code": "証券コードの形式が正しくありません",
        "too_short": "入力が短すぎます",
        "too_long": "入力が長すぎます",
        "please_try_again": "もう一度お試しください",
        "contact_support": "問題が解決しない場合は、サポートにお問い合わせください",
    }

    # ========================================
    # 設定
    # ========================================
    SETTINGS = {
        "settings": "設定",
        "general": "一般",
        "appearance": "外観",
        "theme": "テーマ",
        "light_mode": "ライトモード",
        "dark_mode": "ダークモード",
        "auto_mode": "自動（システム設定に従う）",
        "language": "言語",
        "timezone": "タイムゾーン",
        "currency": "通貨",
        "date_format": "日付形式",
        "number_format": "数値形式",
        "privacy": "プライバシー",
        "security": "セキュリティ",
        "notifications": "通知",
        "preferences": "環境設定",
        "advanced": "詳細設定",
        "save_settings": "設定を保存",
        "settings_saved": "設定を保存しました",
        "reset_settings": "設定をリセット",
        "reset_confirm": "設定をデフォルトに戻しますか？",
    }

    # ========================================
    # ヘルプ・サポート
    # ========================================
    HELP = {
        "help": "ヘルプ",
        "faq": "よくある質問",
        "tutorial": "チュートリアル",
        "documentation": "ドキュメント",
        "contact_us": "お問い合わせ",
        "support": "サポート",
        "feedback": "フィードバック",
        "report_bug": "バグを報告",
        "feature_request": "機能リクエスト",
        "version": "バージョン",
        "terms_of_service": "利用規約",
        "privacy_policy": "プライバシーポリシー",
    }

    # ========================================
    # 時間・日付
    # ========================================
    TIME = {
        "just_now": "たった今",
        "minutes_ago": "{n}分前",
        "hours_ago": "{n}時間前",
        "days_ago": "{n}日前",
        "weeks_ago": "{n}週間前",
        "months_ago": "{n}ヶ月前",
        "years_ago": "{n}年前",
        "today": "今日",
        "yesterday": "昨日",
        "tomorrow": "明日",
        "this_week": "今週",
        "last_week": "先週",
        "this_month": "今月",
        "last_month": "先月",
        "this_year": "今年",
        "last_year": "昨年",
    }

    @classmethod
    def get(cls, category: str, key: str, **kwargs) -> str:
        """
        メッセージを取得

        Args:
            category: カテゴリ名（例: 'AUTH', 'COMPANY'）
            key: メッセージキー
            **kwargs: メッセージのプレースホルダー値

        Returns:
            メッセージ文字列
        """
        category_dict = getattr(cls, category, {})
        message = category_dict.get(key, f"[{category}.{key}]")

        # プレースホルダーの置換
        if kwargs:
            try:
                message = message.format(**kwargs)
            except KeyError:
                pass

        return message

    @classmethod
    def get_all(cls, category: str) -> Dict[str, str]:
        """
        カテゴリ内のすべてのメッセージを取得

        Args:
            category: カテゴリ名

        Returns:
            メッセージ辞書
        """
        return getattr(cls, category, {})


# エイリアス（短縮形）
msg = Messages.get
msgs = Messages.get_all


# 使用例
if __name__ == "__main__":
    print("=== 日本語メッセージ定義 ===\n")

    # 個別メッセージの取得
    print("ログインメッセージ:", msg("AUTH", "login_success"))
    print("エラーメッセージ:", msg("ERRORS", "not_found"))
    print("お気に入り追加:", msg("FAVORITES", "favorite_added"))

    # プレースホルダー付き
    print("時間表示:", msg("TIME", "minutes_ago", n=5))

    # カテゴリ全体の取得
    print("\n共通メッセージ一覧:")
    for key, value in msgs("COMMON").items():
        print(f"  {key}: {value}")
