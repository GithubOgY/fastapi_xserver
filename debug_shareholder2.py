"""
プレーンテキストパーサーの詳細デバッグ
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
from bs4 import BeautifulSoup

text_content = """（６）【大株主の状況】2025年３月31日現在氏名又は名称住所所有株式数(千株)発行済株式(自己株式を除く)の総数に対する所有株式数の割合(％)日本マスタートラスト信託銀行㈱東京都港区赤坂一丁目８番１号1,805,60513.84㈱豊田自動織機愛知県刈谷市豊田町二丁目１番地1,192,3319.14㈱日本カストディ銀行東京都中央区晴海一丁目８番12号811,6476.22日本生命保険（相）大阪府大阪市中央区今橋三丁目５番12号633,2214.85"""

soup = BeautifulSoup(text_content, "html.parser")
plain_text = soup.get_text()

prefecture_pattern = r'(東京都|北海道|(?:京都|大阪)府|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|埼玉県|千葉県|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|三重県|滋賀県|兵庫県|奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)'

clean_text = plain_text.replace('\u3000', '').replace(' ', '')

print(f"Clean text length: {len(clean_text)}")
print(f"First 200 chars: {clean_text[:200]}\n")

parts = re.split(prefecture_pattern, clean_text)

print(f"Split into {len(parts)} parts\n")

for i, part in enumerate(parts[:20]):  # 最初の20個を表示
    print(f"Part {i}: [{part[:100] if len(part) > 100 else part}]")

print(f"\n\n=== Testing number extraction ===\n")

# テストケース
test_strings = [
    "港区赤坂一丁目８番１号1,805,60513.84",
    "刈谷市豊田町二丁目１番地1,192,3319.14",
    "中央区晴海一丁目８番12号811,6476.22",
]

for test_str in test_strings:
    # パターン1: 末尾に数字
    m1 = re.search(r'([\d,]+)([\d.]+)$', test_str)
    print(f"Test: {test_str[:50]}")
    print(f"  Pattern $([\d,]+)([\d.]+)$: {m1.groups() if m1 else 'No match'}")

    # パターン2: 末尾を気にしない
    m2 = re.search(r'([\d,]+)([\d.]+)', test_str)
    print(f"  Pattern ([\d,]+)([\d.]+): {m2.groups() if m2 else 'No match'}")
    print()
