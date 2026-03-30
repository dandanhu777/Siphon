import sys
import traceback
try:
    import fallback_email_sender
    fallback_email_sender.generate_report()
except BaseException as e:
    print(f"Wrapper caught an exception: {type(e).__name__} - {e}")
    traceback.print_exc()
