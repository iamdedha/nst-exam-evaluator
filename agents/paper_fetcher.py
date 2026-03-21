"""
Paper Fetcher: Downloads and extracts text from research papers.
Handles various sources: arXiv, ACM, ACL Anthology, IEEE, direct PDFs.
"""

import os
import re
import time
import hashlib
import requests
from pathlib import Path
from urllib.parse import urlparse

try:
    from PyPDF2 import PdfReader
except ImportError:
    from pypdf import PdfReader

from bs4 import BeautifulSoup

PAPERS_DIR = Path(__file__).parent.parent.parent / "evaluator" / "papers"
PAPERS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def _url_to_filename(url: str, title: str = "") -> str:
    """Generate a safe filename from URL."""
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    safe_title = re.sub(r'[^\w\s-]', '', title[:50]).strip().replace(' ', '_')
    return f"{safe_title}_{h}" if safe_title else h


def _extract_arxiv_id(url: str) -> str:
    """Extract arXiv ID from URL."""
    patterns = [
        r'arxiv\.org/abs/(\d+\.\d+)',
        r'arxiv\.org/pdf/(\d+\.\d+)',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return ""


def fetch_paper_text(url: str, title: str = "") -> dict:
    """
    Fetch paper content and return extracted text.
    Returns dict with 'text', 'source', 'pdf_path', 'status'.
    """
    filename = _url_to_filename(url, title)
    pdf_path = PAPERS_DIR / f"{filename}.pdf"
    text_path = PAPERS_DIR / f"{filename}.txt"

    # Check cache
    if text_path.exists():
        text = text_path.read_text()
        if len(text) > 100:
            return {
                "text": text,
                "source": "cache",
                "pdf_path": str(pdf_path),
                "status": "success",
            }

    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    pdf_url = None
    abstract_text = ""

    try:
        # --- arXiv ---
        if "arxiv.org" in domain:
            arxiv_id = _extract_arxiv_id(url)
            if arxiv_id:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                # Also get abstract
                try:
                    abs_resp = requests.get(f"https://arxiv.org/abs/{arxiv_id}", headers=HEADERS, timeout=(5, 15))
                    if abs_resp.status_code == 200:
                        soup = BeautifulSoup(abs_resp.text, "html.parser")
                        abs_block = soup.find("blockquote", class_="abstract")
                        if abs_block:
                            abstract_text = abs_block.get_text().replace("Abstract:", "").strip()
                except Exception:
                    pass

        # --- ACL Anthology ---
        elif "aclanthology.org" in domain or "aclweb.org" in domain:
            if not url.endswith(".pdf"):
                pdf_url = url.rstrip("/") + ".pdf"
            else:
                pdf_url = url

        # --- ACM Digital Library ---
        elif "dl.acm.org" in domain:
            # Try to get the PDF link from the page
            try:
                resp = requests.get(url, headers=HEADERS, timeout=(5, 15), allow_redirects=True)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Extract abstract
                    abs_div = soup.find("div", class_="abstractSection")
                    if abs_div:
                        abstract_text = abs_div.get_text().strip()
                    # Try PDF link
                    pdf_link = soup.find("a", {"title": re.compile("PDF", re.I)})
                    if pdf_link and pdf_link.get("href"):
                        pdf_url = "https://dl.acm.org" + pdf_link["href"]
            except Exception:
                pass

        # --- IEEE ---
        elif "ieee.org" in domain or "ieeexplore" in domain:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=(5, 15))
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    abs_div = soup.find("div", class_="abstract-text")
                    if abs_div:
                        abstract_text = abs_div.get_text().strip()
            except Exception:
                pass

        # --- JMLR ---
        elif "jmlr.org" in domain:
            if not url.endswith(".pdf"):
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=(5, 15))
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        pdf_link = soup.find("a", href=re.compile(r"\.pdf$"))
                        if pdf_link:
                            pdf_url = pdf_link["href"]
                            if not pdf_url.startswith("http"):
                                pdf_url = f"https://jmlr.org{pdf_url}"
                except Exception:
                    pass
            else:
                pdf_url = url

        # --- NeurIPS / NIPS proceedings ---
        elif "proceedings.neurips.cc" in domain or "papers.nips.cc" in domain:
            if not url.endswith(".pdf"):
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=(5, 15))
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        pdf_link = soup.find("a", href=re.compile(r"\.pdf"))
                        if pdf_link:
                            href = pdf_link["href"]
                            if not href.startswith("http"):
                                href = f"https://proceedings.neurips.cc{href}"
                            pdf_url = href
                        abs_div = soup.find("p", class_="abstract")
                        if abs_div:
                            abstract_text = abs_div.get_text().strip()
                except Exception:
                    pass
            else:
                pdf_url = url

        # --- SpringerLink ---
        elif "springer" in domain or "link.springer" in domain:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=(5, 15))
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    abs_section = soup.find("section", {"data-title": "Abstract"})
                    if abs_section:
                        abstract_text = abs_section.get_text().strip()
                    pdf_link = soup.find("a", {"data-track-action": "download pdf"})
                    if pdf_link and pdf_link.get("href"):
                        pdf_url = "https://link.springer.com" + pdf_link["href"]
            except Exception:
                pass

        # --- Direct PDF link ---
        elif url.endswith(".pdf"):
            pdf_url = url

        # --- Generic: try to find abstract on page ---
        else:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=(5, 15), allow_redirects=True)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Look for abstract
                    for sel in ["abstract", "abstractSection", "Abstract"]:
                        block = soup.find(["div", "p", "section", "blockquote"], class_=re.compile(sel, re.I))
                        if block:
                            abstract_text = block.get_text().strip()
                            break
                    # Look for PDF link
                    pdf_link = soup.find("a", href=re.compile(r"\.pdf"))
                    if pdf_link and pdf_link.get("href"):
                        href = pdf_link["href"]
                        if not href.startswith("http"):
                            href = f"{parsed.scheme}://{parsed.netloc}{href}"
                        pdf_url = href
            except Exception:
                pass

        # --- Download PDF ---
        full_text = ""
        if pdf_url and not pdf_path.exists():
            try:
                print(f"    Downloading PDF from {pdf_url[:80]}...")
                resp = requests.get(pdf_url, headers=HEADERS, timeout=(5, 25), allow_redirects=True)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    pdf_path.write_bytes(resp.content)
                    print(f"    Saved PDF ({len(resp.content)} bytes)")
                else:
                    print(f"    PDF download failed: status={resp.status_code}, size={len(resp.content)}")
            except Exception as e:
                print(f"    PDF download error: {e}")

        # --- Extract text from PDF ---
        if pdf_path.exists():
            try:
                reader = PdfReader(str(pdf_path))
                pages_text = []
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        pages_text.append(t)
                full_text = "\n\n".join(pages_text)
                print(f"    Extracted {len(full_text)} chars from {len(reader.pages)} pages")
            except Exception as e:
                print(f"    PDF extraction error: {e}")

        # Combine abstract + full text
        combined = ""
        if abstract_text:
            combined = f"ABSTRACT:\n{abstract_text}\n\n"
        if full_text:
            combined += f"FULL TEXT:\n{full_text}"
        elif abstract_text:
            combined = abstract_text
        else:
            combined = ""

        if combined:
            # Cache the extracted text
            text_path.write_text(combined)
            return {
                "text": combined,
                "source": "fetched",
                "pdf_path": str(pdf_path) if pdf_path.exists() else "",
                "status": "success",
            }
        else:
            return {
                "text": "",
                "source": "failed",
                "pdf_path": "",
                "status": "failed",
                "error": f"Could not extract text from {url}",
            }

    except Exception as e:
        return {
            "text": "",
            "source": "error",
            "pdf_path": "",
            "status": "error",
            "error": str(e),
        }


if __name__ == "__main__":
    # Test with a sample paper
    result = fetch_paper_text(
        "https://arxiv.org/abs/1111.0352",
        "Revisiting k-means New Algorithms via Bayesian Nonparametrics"
    )
    print(f"Status: {result['status']}")
    print(f"Text length: {len(result['text'])}")
    print(f"First 500 chars: {result['text'][:500]}")
