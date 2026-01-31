"""
Ground Truth Annotation Tool for PageIndex Testing

This script helps create manual annotations for test PDFs to establish
baseline accuracy measurements.

Usage:
    cd lib/docmind-ai/tests
    python create_ground_truth.py
"""

import json
from pathlib import Path
from typing import Dict, List


def print_header(text: str, char: str = "="):
    """Print a formatted header."""
    print(f"\n{char * 60}")
    print(f"{text}")
    print(f"{char * 60}\n")


def annotate_pdf(pdf_name: str, existing_annotation: Dict = None) -> Dict:
    """
    Interactive annotation of a PDF's expected structure.
    
    Args:
        pdf_name: Name of the PDF file
        existing_annotation: Existing annotation to edit (optional)
    
    Returns:
        Dictionary containing annotation data
    """
    print_header(f"Annotating: {pdf_name}")
    
    # Initialize or load existing annotation
    if existing_annotation:
        print("Found existing annotation. Press Enter to keep existing values.\n")
        annotation = existing_annotation.copy()
    else:
        annotation = {
            "pdf_name": pdf_name,
            "total_pages": 0,
            "has_toc": False,
            "toc_pages": [],
            "chapters": []
        }
    
    # Get total pages
    default_pages = annotation.get("total_pages", "")
    total_pages_input = input(f"Total pages in PDF [{default_pages}]: ").strip()
    annotation["total_pages"] = int(total_pages_input) if total_pages_input else annotation.get("total_pages", 0)
    
    # Check if has TOC
    default_has_toc = "yes" if annotation.get("has_toc") else "no"
    has_toc_input = input(f"Has Table of Contents? (yes/no) [{default_has_toc}]: ").strip().lower()
    annotation["has_toc"] = (has_toc_input == "yes") if has_toc_input else annotation.get("has_toc", False)
    
    # Get TOC pages if applicable
    if annotation["has_toc"]:
        default_toc = ",".join(map(str, annotation.get("toc_pages", [])))
        toc_pages_input = input(f"TOC page numbers (comma-separated, 1-based) [{default_toc}]: ").strip()
        if toc_pages_input:
            annotation["toc_pages"] = [int(p.strip()) for p in toc_pages_input.split(',')]
    
    # Get chapter information
    print("\n" + "-" * 60)
    print("Chapter Annotation")
    print("-" * 60)
    print("Enter chapter information (press Enter on title to finish)")
    print("Tip: Open the PDF in a viewer to reference page numbers\n")
    
    if annotation.get("chapters"):
        print(f"Existing chapters: {len(annotation['chapters'])}")
        keep_existing = input("Keep existing chapters? (yes/no) [yes]: ").strip().lower()
        if keep_existing == "no":
            annotation["chapters"] = []
    
    chapter_num = len(annotation["chapters"]) + 1
    
    while True:
        print(f"\n--- Chapter {chapter_num} ---")
        title = input("  Title (or Enter to finish): ").strip()
        if not title:
            break
        
        start_page = input(f"  Start page for '{title}': ").strip()
        if not start_page:
            print("  Skipped (no start page)")
            continue
            
        end_page = input(f"  End page for '{title}': ").strip()
        if not end_page:
            print("  Skipped (no end page)")
            continue
        
        structure = input(f"  Structure index (e.g., '1', '1.1', '2') [auto]: ").strip()
        if not structure:
            # Auto-generate structure index
            structure = str(chapter_num)
        
        annotation["chapters"].append({
            "title": title,
            "start_page": int(start_page),
            "end_page": int(end_page),
            "structure": structure
        })
        
        chapter_num += 1
    
    # Summary
    print("\n" + "=" * 60)
    print("Annotation Summary")
    print("=" * 60)
    print(f"PDF: {pdf_name}")
    print(f"Total Pages: {annotation['total_pages']}")
    print(f"Has TOC: {annotation['has_toc']}")
    if annotation['has_toc']:
        print(f"TOC Pages: {annotation['toc_pages']}")
    print(f"Chapters Annotated: {len(annotation['chapters'])}")
    print()
    
    return annotation


def display_menu(pdf_files: List[Path], ground_truth: Dict) -> str:
    """Display menu and get user selection."""
    print_header("Ground Truth Annotation Tool", "=")
    print(f"Found {len(pdf_files)} PDF files\n")
    
    for i, pdf in enumerate(pdf_files, 1):
        status = "✓ Annotated" if pdf.name in ground_truth else "○ Not annotated"
        chapters = len(ground_truth.get(pdf.name, {}).get("chapters", []))
        chapters_str = f"({chapters} chapters)" if chapters > 0 else ""
        print(f"{i:2d}. {pdf.name:50s} [{status}] {chapters_str}")
    
    print("\nOptions:")
    print("  • Enter PDF numbers to annotate (comma-separated)")
    print("  • Type 'all' to annotate all unannotated PDFs")
    print("  • Type 'quit' to exit")
    print()
    
    return input("Your choice: ").strip()


def main():
    """Main function to run the annotation tool."""
    # Setup paths
    script_dir = Path(__file__).parent
    test_pdfs_dir = script_dir / "pdfs"
    ground_truth_file = script_dir / "ground_truth.json"
    
    # Ensure test PDFs directory exists
    if not test_pdfs_dir.exists():
        print(f"Error: Test PDFs directory not found: {test_pdfs_dir}")
        print("Please create it and add PDF files to annotate.")
        return
    
    # Load existing annotations
    if ground_truth_file.exists():
        with open(ground_truth_file, 'r', encoding='utf-8') as f:
            ground_truth = json.load(f)
        print(f"Loaded existing annotations from {ground_truth_file}")
    else:
        ground_truth = {}
        print("No existing annotations found. Starting fresh.")
    
    # Get list of PDFs
    pdf_files = sorted(test_pdfs_dir.glob("*.pdf"))
    
    if not pdf_files:
        print(f"Error: No PDF files found in {test_pdfs_dir}")
        return
    
    # Main loop
    while True:
        selection = display_menu(pdf_files, ground_truth)
        
        if selection.lower() == 'quit':
            print("\nExiting without saving.")
            break
        
        # Determine which PDFs to annotate
        pdfs_to_annotate = []
        
        if selection.lower() == 'all':
            pdfs_to_annotate = [pdf for pdf in pdf_files if pdf.name not in ground_truth]
            if not pdfs_to_annotate:
                print("\nAll PDFs are already annotated!")
                input("Press Enter to continue...")
                continue
        else:
            try:
                indices = [int(i.strip()) - 1 for i in selection.split(',')]
                pdfs_to_annotate = [pdf_files[i] for i in indices if 0 <= i < len(pdf_files)]
            except (ValueError, IndexError):
                print("\nInvalid selection! Please try again.")
                input("Press Enter to continue...")
                continue
        
        if not pdfs_to_annotate:
            print("\nNo PDFs selected.")
            input("Press Enter to continue...")
            continue
        
        # Annotate selected PDFs
        for pdf in pdfs_to_annotate:
            existing = ground_truth.get(pdf.name)
            annotation = annotate_pdf(pdf.name, existing)
            ground_truth[pdf.name] = annotation
            
            # Save after each annotation
            with open(ground_truth_file, 'w', encoding='utf-8') as f:
                json.dump(ground_truth, f, indent=2, ensure_ascii=False)
            
            print(f"\n✓ Saved annotation for {pdf.name}")
        
        print(f"\n{len(pdfs_to_annotate)} PDF(s) annotated successfully!")
        
        # Ask if user wants to continue
        continue_input = input("\nAnnotate more PDFs? (yes/no) [yes]: ").strip().lower()
        if continue_input == "no":
            break
    
    # Final summary
    print_header("Annotation Complete", "=")
    print(f"Ground truth saved to: {ground_truth_file}")
    print(f"Total annotated PDFs: {len(ground_truth)}")
    print(f"Total chapters: {sum(len(gt.get('chapters', [])) for gt in ground_truth.values())}")
    print("\nYou can now run baseline measurements with these annotations.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
