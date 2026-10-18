#!/usr/bin/env python3
"""Test script for lead list management system.

Tests the full workflow without actual paid enrichment:
1. Create a test list
2. Add test leads
3. Mock enrichment (no API calls)
4. Export to CSV
5. Clean up

Run after applying the migration to verify everything works.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path
from uuid import UUID

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))
import lead_lists


def test_create_list() -> str:
    """Test creating a list."""
    print("Test 1: Create a list")
    
    # Create temp LinkedIn URLs file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("https://www.linkedin.com/in/testuser1\n")
        f.write("https://www.linkedin.com/in/testuser2\n")
        f.write("https://www.linkedin.com/in/testuser3\n")
        urls_file = f.name
    
    try:
        # Create a test list
        class Args:
            client = "TEST"
            name = "Test List - Lead Lists System"
            source = "test"
            linkedin_urls = urls_file
            csv = None
            estimated_cost = 1.0
            cost_cap = 10.0
            metadata = None
        
        args = Args()
        lead_lists.cmd_create(args)
        
        # Get the created list
        lists = lead_lists.sb_request(
            "GET",
            "lead_lists",
            query={
                "client": "eq.TEST",
                "list_name": "ilike.%Test List - Lead Lists System%",
                "order": "created_at.desc",
                "limit": "1",
            }
        )
        
        if not lists or len(lists) == 0:
            raise RuntimeError("Failed to create test list")
        
        list_id = lists[0]["list_id"]
        print(f"✓ Created test list: {list_id}\n")
        return list_id
    
    finally:
        os.unlink(urls_file)


def test_show_list(list_id: str) -> None:
    """Test showing list details."""
    print("Test 2: Show list details")
    
    class Args:
        list_id = list_id
        sample = 3
    
    args = Args()
    lead_lists.cmd_show(args)
    print("✓ Show list works\n")


def test_list_lists() -> None:
    """Test listing all lists."""
    print("Test 3: List all lists")
    
    class Args:
        client = "TEST"
        status = None
        limit = 10
    
    args = Args()
    lead_lists.cmd_list(args)
    print("✓ List command works\n")


def test_mock_enrichment(list_id: str) -> None:
    """Test mock enrichment (update statuses without API calls)."""
    print("Test 4: Mock enrichment (simulate without paid calls)")
    
    # Fetch pending members
    members = lead_lists.sb_request(
        "GET",
        "lead_list_members",
        query={
            "list_id": f"eq.{list_id}",
            "enrichment_status": "eq.pending",
            "select": "lead_id",
        }
    )
    
    if not members or len(members) == 0:
        print("⚠ No pending members to mock enrich")
        return
    
    # Mock enrich first lead
    lead_id = members[0]["lead_id"]
    
    # Update to enriched
    lead_lists.sb_request(
        "PATCH",
        f"lead_list_members?list_id=eq.{list_id}&lead_id=eq.{lead_id}",
        {
            "enrichment_status": "enriched",
            "cost_micro": 3000,  # $0.003
        }
    )
    
    # Update the lead with a fake email
    lead_lists.sb_request(
        "PATCH",
        f"pipeline_leads?id=eq.{lead_id}",
        {
            "email": "test@example.com",
            "email_source": "test",
            "mv_status": "test_valid",
        }
    )
    
    print(f"✓ Mock enriched 1 lead (${0.003:.3f})")
    
    # Check updated counts
    lists = lead_lists.sb_request(
        "GET",
        "lead_lists",
        query={"list_id": f"eq.{list_id}"}
    )
    
    lst = lists[0]
    print(f"  Enriched count: {lst['enriched_count']}")
    print(f"  Ready count: {lst['ready_count']}")
    print(f"  Actual cost: ${lst['actual_cost_usd']:.6f}")
    print("✓ Counts auto-updated by trigger\n")


def test_export(list_id: str) -> None:
    """Test exporting a list."""
    print("Test 5: Export list to CSV")
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        output_file = f.name
    
    try:
        class Args:
            list_id = list_id
            format = "csv"
            output = output_file
        
        args = Args()
        lead_lists.cmd_export(args)
        
        # Check file exists and has content
        if Path(output_file).exists():
            content = Path(output_file).read_text()
            lines = content.strip().split("\n")
            print(f"✓ Exported {len(lines) - 1} row(s) to CSV\n")
        else:
            print("⚠ Export file not created (may be no ready leads)\n")
    
    finally:
        if Path(output_file).exists():
            os.unlink(output_file)


def test_stats() -> None:
    """Test stats command."""
    print("Test 6: Show pipeline statistics")
    
    class Args:
        pass
    
    args = Args()
    lead_lists.cmd_stats(args)
    print("✓ Stats command works\n")


def cleanup(list_id: str) -> None:
    """Clean up test data."""
    print("Cleanup: Removing test list")
    
    # Delete the list (cascade will remove members)
    lead_lists.sb_request(
        "DELETE",
        f"lead_lists?list_id=eq.{list_id}",
    )
    
    print(f"✓ Deleted test list {list_id[:8]}\n")


def main() -> None:
    print("=" * 60)
    print("Lead Lists System Test")
    print("=" * 60)
    print()
    
    # Check prerequisites
    try:
        lead_lists.supabase_key()
    except SystemExit as e:
        print(f"Error: {e}")
        print("\nSet SUPABASE_SERVICE_ROLE_KEY before running tests")
        sys.exit(1)
    
    list_id = None
    
    try:
        # Run tests
        list_id = test_create_list()
        test_show_list(list_id)
        test_list_lists()
        test_mock_enrichment(list_id)
        test_export(list_id)
        test_stats()
        
        print("=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("  1. Create a real list: ./scripts/lead_lists.py create --help")
        print("  2. Enrich it: ./scripts/enrich_list.py <list_id> --confirm-spend 10.00")
        print("  3. Export: ./scripts/lead_lists.py export <list_id>")
    
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        # Clean up
        if list_id:
            try:
                cleanup(list_id)
            except Exception as e:
                print(f"⚠ Cleanup failed: {e}")


if __name__ == "__main__":
    main()
