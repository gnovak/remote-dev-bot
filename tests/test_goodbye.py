import subprocess
import sys

def test_goodbye_script():
    """Test that goodbye.py prints the correct message."""
    result = subprocess.run(
        [sys.executable, 'goodbye.py'],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, "Script should exit successfully"
    assert result.stdout.strip() == 'Goodbye from Remote Dev Bot', \
        f"Expected 'Goodbye from Remote Dev Bot', got '{result.stdout.strip()}'"

if __name__ == '__main__':
    test_goodbye_script()
    print("Test passed!")
