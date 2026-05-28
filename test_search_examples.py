#!/usr/bin/env python3
"""
Simple test examples for the Google Search MCP server.

Run this script to test various search capabilities:
    python test_search_examples.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path so we can import the server
sys.path.insert(0, str(Path(__file__).parent))

from src.google_search_mcp.server import google_search


async def test_basic_search():
    """Test basic Google search."""
    print("\n" + "="*80)
    print("TEST 1: Basic Search - Python web frameworks")
    print("="*80)
    result = await google_search(
        query="best Python web frameworks",
        num_results=5
    )
    print(result)


async def test_search_with_site():
    """Test search limited to specific site."""
    print("\n" + "="*80)
    print("TEST 2: Search with Site Filter - Reddit discussions")
    print("="*80)
    result = await google_search(
        query="home lab setup",
        site="reddit.com",
        num_results=5
    )
    print(result)


async def test_search_with_time_filter():
    """Test search with time range filter."""
    print("\n" + "="*80)
    print("TEST 3: Search with Time Filter - Past week news")
    print("="*80)
    result = await google_search(
        query="artificial intelligence news",
        time_range="past_week",
        num_results=5
    )
    print(result)


async def test_search_multiple_filters():
    """Test search with multiple filters."""
    print("\n" + "="*80)
    print("TEST 4: Search with Multiple Filters - GitHub repos")
    print("="*80)
    result = await google_search(
        query="rust programming language",
        site="github.com",
        time_range="past_month",
        num_results=5
    )
    print(result)


async def test_search_page_2():
    """Test pagination - get page 2 results."""
    print("\n" + "="*80)
    print("TEST 5: Pagination - Page 2 of results")
    print("="*80)
    result = await google_search(
        query="machine learning tutorials",
        num_results=5,
        page=2
    )
    print(result)


async def test_search_stackoverflow():
    """Test search on Stack Overflow."""
    print("\n" + "="*80)
    print("TEST 6: Stack Overflow Search - Async Python")
    print("="*80)
    result = await google_search(
        query="async await",
        site="stackoverflow.com",
        num_results=5
    )
    print(result)


async def test_search_arxiv():
    """Test search on arXiv papers."""
    print("\n" + "="*80)
    print("TEST 7: arXiv Search - Recent papers on transformers")
    print("="*80)
    result = await google_search(
        query="attention mechanism transformers",
        site="arxiv.org",
        time_range="past_month",
        num_results=5
    )
    print(result)


async def test_search_hacker_news():
    """Test search on Hacker News."""
    print("\n" + "="*80)
    print("TEST 8: Hacker News Search - Recent tech news")
    print("="*80)
    result = await google_search(
        query="machine learning",
        site="news.ycombinator.com",
        num_results=5
    )
    print(result)


async def test_search_with_language():
    """Test search with language specification."""
    print("\n" + "="*80)
    print("TEST 9: Search with Language - German results")
    print("="*80)
    result = await google_search(
        query="künstliche intelligenz",
        language="de",
        num_results=5
    )
    print(result)


async def test_search_with_region():
    """Test search with region specification."""
    print("\n" + "="*80)
    print("TEST 10: Search with Region - UK results")
    print("="*80)
    result = await google_search(
        query="weather forecast",
        region="gb",
        num_results=5
    )
    print(result)


async def run_all_tests():
    """Run all search tests."""
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*78 + "║")
    print("║" + "Google Search MCP Server - Test Examples".center(78) + "║")
    print("║" + " "*78 + "║")
    print("╚" + "="*78 + "╝")
    
    try:
        # Run tests
        await test_basic_search()
        await test_search_with_site()
        await test_search_with_time_filter()
        await test_search_multiple_filters()
        await test_search_page_2()
        await test_search_stackoverflow()
        await test_search_arxiv()
        await test_search_hacker_news()
        await test_search_with_language()
        await test_search_with_region()
        
        print("\n" + "="*80)
        print("✅ All tests completed successfully!")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


async def run_quick_test():
    """Run a quick single test for verification."""
    print("\n" + "="*80)
    print("QUICK TEST: Basic Google Search")
    print("="*80)
    try:
        result = await google_search(
            query="Python programming",
            num_results=3
        )
        print(result)
        print("\n✅ Quick test passed!")
        return 0
    except Exception as e:
        print(f"\n❌ Quick test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Test Google Search MCP server"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run only a quick test"
    )
    parser.add_argument(
        "--test",
        type=int,
        help="Run a specific test (1-10)"
    )
    
    args = parser.parse_args()
    
    if args.quick:
        return asyncio.run(run_quick_test())
    
    if args.test:
        tests = {
            1: test_basic_search,
            2: test_search_with_site,
            3: test_search_with_time_filter,
            4: test_search_multiple_filters,
            5: test_search_page_2,
            6: test_search_stackoverflow,
            7: test_search_arxiv,
            8: test_search_hacker_news,
            9: test_search_with_language,
            10: test_search_with_region,
        }
        
        if args.test in tests:
            return asyncio.run(tests[args.test]())
        else:
            print(f"❌ Invalid test number. Choose 1-10.")
            return 1
    
    # Run all tests
    return asyncio.run(run_all_tests())


if __name__ == "__main__":
    sys.exit(main())
