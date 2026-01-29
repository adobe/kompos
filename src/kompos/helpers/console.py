"""
Console output helpers for consistent, colorful CLI output.
"""
import sys


# ANSI Color Codes
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'
    
    # Background colors
    BG_BLUE = '\033[44m'
    BG_CYAN = '\033[46m'


def print_error(message, details=None):
    """Print an error message in red."""
    print(f"{Colors.RED}ERROR: {message}{Colors.RESET}", file=sys.stderr)
    if details:
        if isinstance(details, list):
            for detail in details:
                print(detail, file=sys.stderr)
        else:
            print(details, file=sys.stderr)


def print_success(message):
    """Print a success message with checkmark."""
    print(f"{Colors.GREEN}✓{Colors.RESET} {message}")


def print_info(message, indent=0):
    """Print an info message with optional indentation."""
    prefix = "   " * indent
    print(f"{prefix}{message}")


def print_warning(message):
    """Print a warning message in yellow."""
    print(f"{Colors.YELLOW}⚠{Colors.RESET}  {message}")


def print_section_header(title, width=80):
    """Print a section header with separator lines."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'═' * width}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{title}{Colors.RESET}")
    print(f"{Colors.CYAN}{'═' * width}{Colors.RESET}")


def print_subsection(emoji, title, details=None):
    """Print a subsection with emoji and optional details."""
    print()
    print(f"{Colors.BOLD}{emoji} {title}{Colors.RESET}")
    if details:
        if isinstance(details, dict):
            for key, value in details.items():
                print(f"   {Colors.DIM}{key}:{Colors.RESET} {value}")
        elif isinstance(details, list):
            for item in details:
                print(f"   {item}")


def print_separator(width=80):
    """Print a separator line."""
    print(f"{Colors.CYAN}{'═' * width}{Colors.RESET}\n")


def print_summary(total_files=None, composition_files=None, config_files=None, elapsed_time=None, width=80):
    """Print a summary footer with metrics."""
    print(f"{Colors.CYAN}{'═' * width}{Colors.RESET}")
    
    summary_parts = []
    
    # Just show total files, no breakdown
    if total_files is not None:
        summary_parts.append(f"{total_files} files generated")
    
    # Time
    if elapsed_time is not None:
        if elapsed_time < 1:
            time_str = f"{elapsed_time * 1000:.0f}ms"
        else:
            time_str = f"{elapsed_time:.2f}s"
        summary_parts.append(f"{time_str}")
    
    if summary_parts:
        summary = f"{Colors.GREEN}✓{Colors.RESET} {Colors.BOLD}Completed{Colors.RESET}  {Colors.DIM}•{Colors.RESET}  " + f"  {Colors.DIM}•{Colors.RESET}  ".join(summary_parts)
        print(summary)
        print(f"{Colors.CYAN}{'═' * width}{Colors.RESET}\n")
    else:
        print()


def print_kvp(key, value, indent=1, dim_key=True):
    """Print a key-value pair with indentation."""
    prefix = "   " * indent
    if dim_key:
        print(f"{prefix}{Colors.DIM}{key}:{Colors.RESET} {value}")
    else:
        print(f"{prefix}{key}: {value}")


def format_config_path(path):
    """
    Format a hierarchical config path with colored keys and values.
    
    Example: configs/cloud=aws/project=demo/env=dev
    Returns: configs/cloud=aws/project=demo/env=dev with colors
    """
    if not path:
        return path
    
    parts = path.split('/')
    formatted_parts = []
    
    for part in parts:
        if '=' in part:
            key, value = part.split('=', 1)
            # Key in normal green, value in bold
            formatted_parts.append(f"{Colors.GREEN}{key}={Colors.RESET}{Colors.BOLD}{value}{Colors.RESET}")
        else:
            # No '=' means it's just a directory name
            formatted_parts.append(part)
    
    return '/'.join(formatted_parts)


# Specialized formatters for common Kompos operations

def print_composition_header(composition_name, composition_type=None, source=None, target=None, config_path=None):
    """Print a composition generation header with detailed info."""
    # Compact header with composition info
    if composition_type:
        title = f"TFE Composition: {Colors.GREEN}{Colors.BOLD}{composition_name}{Colors.RESET} {Colors.GREEN}({composition_type}){Colors.RESET}"
    else:
        title = f"TFE Composition: {Colors.GREEN}{Colors.BOLD}{composition_name}{Colors.RESET}"
    
    print()
    print(f"{Colors.CYAN}{'═' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{title}")
    print(f"{Colors.CYAN}{'═' * 80}{Colors.RESET}")
    
    if config_path:
        formatted_path = format_config_path(config_path)
        print(f"   {Colors.DIM}Config:{Colors.RESET} {formatted_path}")
    
    # Paths section - will show success inline
    if source or target:
        print()
        if source:
            print(f"   {Colors.DIM}Source:{Colors.RESET} {source}")
        if target:
            print(f"   {Colors.DIM}Target:{Colors.RESET} {Colors.GREEN}{target}{Colors.RESET}")
    print()


def print_file_generation(file_type, output_path, format_type=None, size=None):
    """Print file generation info without format (compact)."""
    print(f"  • {file_type}: {output_path}")
    if size:
        print(f"    {Colors.DIM}Size:{Colors.RESET} {size}")
