
from index_service import get_benchmark_return
from datetime import datetime

print("--- Debug Index Service ---")
today = datetime.now().strftime("%Y-%m-%d")
print(f"Today: {today}")

# Test T+0 (Today)
ret_t0 = get_benchmark_return(today)
print(f"T+0 ({today}): {ret_t0}")

# Test T+1 (Yesterday 2026-01-28)
ret_t1 = get_benchmark_return("2026-01-28")
print(f"T+1 (2026-01-28): {ret_t1}")

# Test T+10 (2026-01-15)
ret_t10 = get_benchmark_return("2026-01-15")
print(f"T+10 (2026-01-15): {ret_t10}")
