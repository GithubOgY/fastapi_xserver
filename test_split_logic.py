"""
Test the correct split logic for concatenated share numbers and ratios
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re

test_cases = [
    ("1,805,60513.84", "1,805,605", "13.84"),
    ("1,192,3319.14", "1,192,331", "9.14"),
    ("811,6476.22", "811,647", "6.22"),
    ("633,2214.85", "633,221", "4.85"),
]

print("HYPOTHESIS: shares and ratio are concatenated by merging last digit of shares with first digit of ratio\n")
print("Example: 1,805,605 (shares) + 13.84 (ratio) → 1,805,60513.84\n")
print("="*70 + "\n")

for combined_str, expected_shares, expected_ratio in test_cases:
    # Remove commas for easier processing
    no_commas = combined_str.replace(',', '')

    # Try both strategies and pick the one where shares properly align with comma groups
    candidates = []

    # Strategy 1: 2-digit ratio (XX.XX) - no digit sharing, extract last 5 chars
    if len(no_commas) >= 5:
        ratio_candidate = no_commas[-5:]  # e.g., "13.84"
        if '.' in ratio_candidate and ratio_candidate.count('.') == 1:
            parts = ratio_candidate.split('.')
            if len(parts[0]) == 2 and len(parts[1]) == 2:
                try:
                    ratio_float = float(ratio_candidate)
                    if 0 < ratio_float < 100:
                        shares_part = no_commas[:-5]
                        # Check if shares_part length is divisible by 3 or has pattern X,XXX,XXX
                        shares_len = len(shares_part)
                        # After first digit(s), remaining should be groups of 3
                        # e.g., 1805605 → 1,805,605 (len=7, first_group=1, remaining=6 digits = 2 groups of 3)
                        first_group_len = shares_len % 3 if shares_len % 3 != 0 else 3
                        remaining_len = shares_len - first_group_len
                        is_valid_grouping = remaining_len % 3 == 0

                        if is_valid_grouping:
                            candidates.append((shares_part, ratio_candidate, 'two-digit'))
                except ValueError:
                    pass

    # Strategy 2: 1-digit ratio (X.XX) - first digit shared, extract last 4 chars, prepend to shares
    if len(no_commas) >= 4:
        ratio_candidate = no_commas[-4:]  # e.g., "9.14"
        if '.' in ratio_candidate and ratio_candidate.count('.') == 1:
            parts = ratio_candidate.split('.')
            if len(parts[0]) == 1 and len(parts[1]) == 2:
                try:
                    ratio_float = float(ratio_candidate)
                    if 0 < ratio_float < 100:
                        shares_part = no_commas[:-4]
                        ratio_first_digit = ratio_candidate[0]
                        reconstructed_shares = shares_part + ratio_first_digit

                        # Check if reconstructed_shares has valid grouping
                        shares_len = len(reconstructed_shares)
                        first_group_len = shares_len % 3 if shares_len % 3 != 0 else 3
                        remaining_len = shares_len - first_group_len
                        is_valid_grouping = remaining_len % 3 == 0

                        if is_valid_grouping:
                            candidates.append((reconstructed_shares, ratio_candidate, 'one-digit'))
                except ValueError:
                    pass

    # Pick the best candidate (prefer the one with valid grouping, or the first one)
    reconstructed_shares_with_commas = None
    ratio_value = None

    print(f"  DEBUG: Found {len(candidates)} candidates")
    for idx, (shares_no_comma, ratio_str, strategy) in enumerate(candidates):
        print(f"    Candidate {idx+1} ({strategy}): shares={shares_no_comma}, ratio={ratio_str}")

    if candidates:
        # Prefer 1-digit ratio (last candidate is usually 1-digit if both exist)
        # Since we append 2-digit first, then 1-digit, reverse to prefer 1-digit
        shares_no_comma, ratio_str, _ = candidates[-1]  # Take LAST candidate (1-digit if both exist)
        reconstructed_shares_with_commas = ""
        for i, digit in enumerate(reversed(shares_no_comma)):
            if i > 0 and i % 3 == 0:
                reconstructed_shares_with_commas = ',' + reconstructed_shares_with_commas
            reconstructed_shares_with_commas = digit + reconstructed_shares_with_commas
        ratio_value = ratio_str

    if reconstructed_shares_with_commas and ratio_value:
        status = "✅" if reconstructed_shares_with_commas == expected_shares and ratio_value == expected_ratio else "❌"

        print(f"{status} Combined: {combined_str}")
        print(f"   Expected → shares: {expected_shares}, ratio: {expected_ratio}")
        print(f"   Got      → shares: {reconstructed_shares_with_commas}, ratio: {ratio_value}")
        print()
    else:
        print(f"❌ Combined: {combined_str} - Failed to parse")
        print()
