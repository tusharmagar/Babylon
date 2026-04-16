#!/usr/bin/env python3
"""
Comprehensive backend testing for YouTube-to-Laser pipeline.
Tests both service modules and API endpoints.
"""
import sys
import os
import json
import time
import requests
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, '/app/backend')

# Test configuration
BACKEND_URL = "https://youtube-to-laser.preview.emergentagent.com/api"
TEST_YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

def test_service_modules():
    """Test individual service modules by importing and calling them directly."""
    print("=" * 60)
    print("TESTING SERVICE MODULES")
    print("=" * 60)
    
    results = {}
    
    # Test 1: Text renderer
    print("\n1. Testing text_renderer...")
    try:
        from services.text_renderer import text_to_points
        pts = text_to_points('HELLO', 0, 0, 800.0, (0, 255, 0))
        point_count = len(pts)
        print(f"   ✅ text_to_points('HELLO') returned {point_count} points")
        results['text_renderer'] = {'success': True, 'points': point_count, 'expected_min': 30}
        if point_count < 30:
            print(f"   ⚠️  Warning: Expected >30 points, got {point_count}")
    except Exception as e:
        print(f"   ❌ text_renderer failed: {e}")
        results['text_renderer'] = {'success': False, 'error': str(e)}
    
    # Test 2: Effects
    print("\n2. Testing effects...")
    try:
        from services.effects import lissajous, spiral, beam_fan, tunnel
        liss_pts = lissajous(0, (255, 0, 200))
        spiral_pts = spiral(0, (0, 255, 100))
        fan_pts = beam_fan(0, (0, 150, 255))
        tunnel_pts = tunnel(0, (255, 255, 0))
        
        counts = [len(liss_pts), len(spiral_pts), len(fan_pts), len(tunnel_pts)]
        print(f"   ✅ Effects returned points: lissajous={counts[0]}, spiral={counts[1]}, beam_fan={counts[2]}, tunnel={counts[3]}")
        results['effects'] = {'success': True, 'point_counts': counts}
        
        if any(c == 0 for c in counts):
            print(f"   ⚠️  Warning: Some effects returned 0 points")
    except Exception as e:
        print(f"   ❌ effects failed: {e}")
        results['effects'] = {'success': False, 'error': str(e)}
    
    # Test 3: Point optimizer
    print("\n3. Testing point_optimizer...")
    try:
        from services.point_optimizer import optimize_frame
        from services.text_renderer import text_to_points
        pts = text_to_points('TEST', 0, 0, 800.0, (0, 255, 0))
        original_count = len(pts)
        opt = optimize_frame(pts)
        optimized_count = len(opt)
        print(f"   ✅ Point optimizer: {original_count} -> {optimized_count} points")
        results['point_optimizer'] = {'success': True, 'original': original_count, 'optimized': optimized_count}
        
        if optimized_count <= original_count:
            print(f"   ⚠️  Warning: Expected point count to increase, got {original_count} -> {optimized_count}")
    except Exception as e:
        print(f"   ❌ point_optimizer failed: {e}")
        results['point_optimizer'] = {'success': False, 'error': str(e)}
    
    # Test 4: ILDA writer
    print("\n4. Testing ilda_writer...")
    try:
        from services.ilda_writer import write_ilda_file
        from models.laser_types import LaserFrame, LaserPoint
        
        frames = [LaserFrame(
            points=[
                LaserPoint(x=0, y=0, r=255, g=0, b=0, blanked=False),
                LaserPoint(x=10000, y=10000, r=0, g=255, b=0, blanked=False)
            ],
            timestamp_ms=0
        )]
        
        test_path = Path('/tmp/test.ild')
        file_size = write_ilda_file(frames, test_path)
        print(f"   ✅ ILDA writer: File size {file_size} bytes")
        results['ilda_writer'] = {'success': True, 'file_size': file_size, 'expected_min': 50}
        
        if file_size < 50:
            print(f"   ⚠️  Warning: Expected >50 bytes, got {file_size}")
    except Exception as e:
        print(f"   ❌ ilda_writer failed: {e}")
        results['ilda_writer'] = {'success': False, 'error': str(e)}
    
    # Test 5: Lyrics parsing
    print("\n5. Testing lyrics...")
    try:
        from services.lyrics import parse_lrc
        lrc_content = "[00:10.00]Hello world\n[00:15.00]This is a test"
        lines = parse_lrc(lrc_content, 120.0)
        line_count = len(lines)
        first_line = lines[0] if lines else None
        word_count = len(first_line.words) if first_line else 0
        
        print(f"   ✅ Lyrics parser: {line_count} lines, first line: '{first_line.text if first_line else 'None'}', words: {word_count}")
        results['lyrics'] = {'success': True, 'lines': line_count, 'words': word_count, 'expected_lines': 2}
        
        if line_count != 2:
            print(f"   ⚠️  Warning: Expected 2 lines, got {line_count}")
    except Exception as e:
        print(f"   ❌ lyrics failed: {e}")
        results['lyrics'] = {'success': False, 'error': str(e)}
    
    return results

def test_api_endpoints():
    """Test API endpoints."""
    print("\n" + "=" * 60)
    print("TESTING API ENDPOINTS")
    print("=" * 60)
    
    results = {}
    
    # Test 1: Laser status
    print("\n1. Testing GET /api/laser/status...")
    try:
        response = requests.get(f"{BACKEND_URL}/laser/status", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Laser status: {response.status_code}, initialized={data.get('initialized')}, simulation={data.get('simulation_mode')}")
            results['laser_status'] = {'success': True, 'status_code': response.status_code, 'data': data}
        else:
            print(f"   ❌ Laser status failed: {response.status_code}")
            results['laser_status'] = {'success': False, 'status_code': response.status_code}
    except Exception as e:
        print(f"   ❌ Laser status failed: {e}")
        results['laser_status'] = {'success': False, 'error': str(e)}
    
    # Test 2: YouTube analyze (SSE endpoint)
    print(f"\n2. Testing POST /api/youtube/analyze with {TEST_YOUTUBE_URL}...")
    print("   Note: This is an SSE endpoint that may take 60-120s. Testing connection establishment...")
    
    try:
        # Use curl-like approach with streaming
        import subprocess
        
        curl_cmd = [
            'curl', '-N', '-X', 'POST',
            f'{BACKEND_URL}/youtube/analyze',
            '-H', 'Content-Type: application/json',
            '-d', json.dumps({'youtube_url': TEST_YOUTUBE_URL}),
            '--max-time', '180',  # 3 minute timeout
            '--connect-timeout', '10'
        ]
        
        print(f"   Running: {' '.join(curl_cmd)}")
        
        # Start the process
        process = subprocess.Popen(
            curl_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Read first few lines to verify SSE connection
        events_received = []
        start_time = time.time()
        timeout = 30  # Wait up to 30 seconds for first events
        
        while time.time() - start_time < timeout:
            try:
                # Check if process is still running
                if process.poll() is not None:
                    break
                
                # Try to read a line with short timeout
                process.stdout.settimeout(1)
                line = process.stdout.readline()
                
                if line:
                    line = line.strip()
                    if line.startswith('data:'):
                        try:
                            event_data = json.loads(line[5:])  # Remove 'data:' prefix
                            events_received.append(event_data)
                            print(f"   📡 SSE Event: {event_data.get('stage', 'unknown')}")
                            
                            # If we get a few events, that's enough to verify it's working
                            if len(events_received) >= 3:
                                break
                        except json.JSONDecodeError:
                            pass
                
            except Exception:
                time.sleep(0.1)
        
        # Terminate the process
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        
        if events_received:
            print(f"   ✅ YouTube analyze SSE: Received {len(events_received)} events")
            print(f"   📋 Events: {[e.get('stage') for e in events_received]}")
            results['youtube_analyze'] = {'success': True, 'events_received': len(events_received), 'events': events_received}
            
            # If we got a complete event, extract job_id for download test
            complete_event = next((e for e in events_received if e.get('stage') == 'complete'), None)
            if complete_event:
                job_id = complete_event.get('job_id')
                if job_id:
                    results['youtube_analyze']['job_id'] = job_id
        else:
            print(f"   ⚠️  YouTube analyze: No SSE events received within {timeout}s")
            results['youtube_analyze'] = {'success': False, 'error': 'No SSE events received'}
    
    except Exception as e:
        print(f"   ❌ YouTube analyze failed: {e}")
        results['youtube_analyze'] = {'success': False, 'error': str(e)}
    
    # Test 3: Job status (if we have a job_id)
    job_id = results.get('youtube_analyze', {}).get('job_id')
    if job_id:
        print(f"\n3. Testing GET /api/youtube/job/{job_id}...")
        try:
            response = requests.get(f"{BACKEND_URL}/youtube/job/{job_id}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Job status: {response.status_code}, status={data.get('status')}")
                results['job_status'] = {'success': True, 'status_code': response.status_code, 'data': data}
            else:
                print(f"   ❌ Job status failed: {response.status_code}")
                results['job_status'] = {'success': False, 'status_code': response.status_code}
        except Exception as e:
            print(f"   ❌ Job status failed: {e}")
            results['job_status'] = {'success': False, 'error': str(e)}
        
        # Test 4: Download (if job is complete)
        if results.get('job_status', {}).get('data', {}).get('status') == 'complete':
            print(f"\n4. Testing GET /api/youtube/download/{job_id}...")
            try:
                response = requests.get(f"{BACKEND_URL}/youtube/download/{job_id}", timeout=10)
                if response.status_code == 200:
                    content_length = len(response.content)
                    print(f"   ✅ Download: {response.status_code}, file size={content_length} bytes")
                    results['download'] = {'success': True, 'status_code': response.status_code, 'file_size': content_length}
                else:
                    print(f"   ❌ Download failed: {response.status_code}")
                    results['download'] = {'success': False, 'status_code': response.status_code}
            except Exception as e:
                print(f"   ❌ Download failed: {e}")
                results['download'] = {'success': False, 'error': str(e)}
    else:
        print("\n3-4. Skipping job status and download tests (no job_id from analyze)")
    
    return results

def print_summary(service_results, api_results):
    """Print test summary."""
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    print("\nSERVICE MODULES:")
    for service, result in service_results.items():
        status = "✅ PASS" if result.get('success') else "❌ FAIL"
        print(f"  {service}: {status}")
        if not result.get('success'):
            print(f"    Error: {result.get('error', 'Unknown error')}")
    
    print("\nAPI ENDPOINTS:")
    for endpoint, result in api_results.items():
        status = "✅ PASS" if result.get('success') else "❌ FAIL"
        print(f"  {endpoint}: {status}")
        if not result.get('success'):
            print(f"    Error: {result.get('error', 'Unknown error')}")
    
    # Overall status
    service_pass = sum(1 for r in service_results.values() if r.get('success'))
    service_total = len(service_results)
    api_pass = sum(1 for r in api_results.values() if r.get('success'))
    api_total = len(api_results)
    
    print(f"\nOVERALL: Services {service_pass}/{service_total}, APIs {api_pass}/{api_total}")
    
    return {
        'services': service_results,
        'apis': api_results,
        'summary': {
            'service_pass': service_pass,
            'service_total': service_total,
            'api_pass': api_pass,
            'api_total': api_total
        }
    }

def main():
    """Run all tests."""
    print("YouTube-to-Laser Pipeline Backend Testing")
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Test YouTube URL: {TEST_YOUTUBE_URL}")
    
    # Test service modules first
    service_results = test_service_modules()
    
    # Test API endpoints
    api_results = test_api_endpoints()
    
    # Print summary
    all_results = print_summary(service_results, api_results)
    
    # Save results to file
    results_file = Path('/app/test_results.json')
    with open(results_file, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\nDetailed results saved to: {results_file}")
    
    return all_results

if __name__ == "__main__":
    main()