"""
株主データ抽出のデバッグスクリプト
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from utils.edinet_enhanced import search_company_reports, process_document
import logging

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s', encoding='utf-8')

# トヨタ自動車の最新決算を取得
result = search_company_reports('7203')
if result and len(result) > 0:
    doc = result[0]
    print(f'\n=== Processing Document: {doc.get("docID")} ===\n')

    # ドキュメントを処理
    data = process_document(doc)

    # 大株主の状況HTMLを確認
    major_sh_html = data.get('text_data', {}).get('大株主の状況', '')

    if major_sh_html:
        print(f'大株主の状況 HTML length: {len(major_sh_html)} characters')
        print(f'\n=== First 1000 characters ===')
        print(major_sh_html[:1000])
        print(f'\n=== Contains <table> tag: {"<table" in major_sh_html} ===')
        print(f'=== Contains <tr> tag: {"<tr" in major_sh_html} ===')
        print(f'=== Contains "株主" keyword: {"株主" in major_sh_html} ===')

        # parse_shareholder_table() を直接呼び出してデバッグ
        from utils.edinet_enhanced import parse_shareholder_table

        print(f'\n=== Calling parse_shareholder_table() ===')
        shareholders = parse_shareholder_table(major_sh_html)
        print(f'Result: {len(shareholders)} shareholders extracted')

        if shareholders:
            for i, sh in enumerate(shareholders[:5], 1):
                print(f'{i}. {sh}')
        else:
            print('\n❌ No shareholders extracted!')
            print('Debugging parse_shareholder_table()...')

            # HTMLをさらに詳しく調査
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(major_sh_html, "html.parser")
            tables = soup.find_all("table")
            print(f'\nNumber of <table> elements found: {len(tables)}')

            for idx, table in enumerate(tables[:3], 1):
                print(f'\n--- Table {idx} ---')
                rows = table.find_all("tr")
                print(f'Number of rows: {len(rows)}')
                if len(rows) > 0:
                    first_row = rows[0]
                    cells = first_row.find_all(["th", "td"])
                    cell_texts = [cell.get_text(strip=True) for cell in cells]
                    print(f'First row cells: {cell_texts}')
    else:
        print('❌ 大株主の状況 not found in text_data!')
else:
    print('❌ No documents found')
