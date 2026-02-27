"""
Data Inspector v7.0.4 — Automated data validation for report integrity.
Extracted from fallback_email_sender.py for modularity.
"""

import os
import datetime
import json


class DataInspector:
    """
    Automated data validation to ensure report integrity.
    Run before email generation to catch issues early.
    """
    def __init__(self, csv_path="siphon_strategy_results.csv"):
        self.csv_path = csv_path
        self.issues = []
        self.warnings = []
        self.passed = []
    
    def check_csv_freshness(self):
        """Check if CSV was updated today."""
        if not os.path.exists(self.csv_path):
            self.issues.append("❌ CSV file missing")
            return False
        
        mtime = os.path.getmtime(self.csv_path)
        mdate = datetime.datetime.fromtimestamp(mtime).date()
        today = datetime.date.today()
        
        if mdate == today:
            self.passed.append(f"✅ CSV fresh (updated {mdate})")
            return True
        else:
            self.warnings.append(f"⚠️ CSV stale (last update: {mdate}, today: {today})")
            return False
    
    def check_index_cache(self):
        """Check if index cache has recent data."""
        cache_file = "index_multi_cache.json"
        if not os.path.exists(cache_file):
            self.issues.append("❌ Index cache missing")
            return False
        
        with open(cache_file, 'r') as f:
            cache = json.load(f)
        
        ssec_data = cache.get("sh000001", {}).get("data", {})
        if not ssec_data:
            self.issues.append("❌ SSEC index data empty")
            return False
        
        dates = sorted(ssec_data.keys())
        latest = dates[-1] if dates else "N/A"
        
        try:
            latest_dt = datetime.datetime.strptime(latest, "%Y-%m-%d").date()
            days_old = (datetime.date.today() - latest_dt).days
            if days_old <= 5:
                self.passed.append(f"✅ Index cache valid (latest: {latest})")
                return True
            else:
                self.warnings.append(f"⚠️ Index cache stale ({days_old} days old)")
                return False
        except Exception:
            self.warnings.append(f"⚠️ Index date parse error: {latest}")
            return False
    
    def check_realtime_index(self):
        """Verify real-time index API is working."""
        try:
            from index_service import get_realtime_index_change
            data = get_realtime_index_change()
            if data and 'sh000001' in data:
                ssec = data['sh000001']
                self.passed.append(f"✅ Real-time index OK (SSEC: {ssec:+.2f}%)")
                return True
            else:
                self.warnings.append("⚠️ Real-time index returned empty")
                return False
        except Exception as e:
            self.issues.append(f"❌ Real-time index error: {e}")
            return False
    
    def check_tracking_data(self, track_data):
        """Validate tracking data integrity."""
        if not track_data:
            self.warnings.append("⚠️ No tracking data available")
            return False
        
        missing_benchmark = 0
        missing_price = 0
        
        for item in track_data:
            idx_str = item.get('index_str', '-')
            if idx_str == '-' or idx_str == '0.00%':
                missing_benchmark += 1
            if item.get('price', 0) == 0:
                missing_price += 1
        
        if missing_benchmark > 0:
            self.warnings.append(f"⚠️ {missing_benchmark}/{len(track_data)} items missing benchmark")
        else:
            self.passed.append(f"✅ All {len(track_data)} items have benchmark data")
        
        if missing_price > 0:
            self.issues.append(f"❌ {missing_price} items have zero price")
            return False
        
        return True
    
    def run_all_checks(self, track_data=None):
        """Run all validation checks and return summary."""
        print("\n" + "="*50)
        print("🔍 DATA INSPECTOR v7.0.4")
        print("="*50)
        
        self.check_csv_freshness()
        self.check_index_cache()
        self.check_realtime_index()
        if track_data:
            self.check_tracking_data(track_data)
        
        for p in self.passed:
            print(f"  {p}")
        for w in self.warnings:
            print(f"  {w}")
        for i in self.issues:
            print(f"  {i}")
        
        print("="*50)
        
        if self.issues:
            print(f"❌ FAILED: {len(self.issues)} critical issues found")
            return False
        elif self.warnings:
            print(f"⚠️ PASSED WITH WARNINGS: {len(self.warnings)} warnings")
            return True
        else:
            print("✅ ALL CHECKS PASSED")
            return True


if __name__ == "__main__":
    inspector = DataInspector()
    inspector.run_all_checks()
