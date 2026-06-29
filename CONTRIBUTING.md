# Contributing to Crypto Oracle AI

Thank you for considering contributing to Crypto Oracle AI! This document provides guidelines and instructions for contributing.

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Keep discussions professional and on-topic

## How to Contribute

### Reporting Bugs

1. Check existing issues first
2. Create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, Python version, etc.)

### Suggesting Features

1. Check existing issues and roadmap
2. Create a feature request issue with:
   - Problem statement
   - Proposed solution
   - Use cases
   - Potential implementation approach

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass (`pytest`)
6. Update documentation if needed
7. Commit with clear messages
8. Push to your fork
9. Open a Pull Request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/your-username/crypto-oracle-ai.git
cd crypto-oracle-ai

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies
pip install pytest pytest-asyncio pytest-cov flake8

# Run tests
pytest

# Run linter
flake8 .
```

## Coding Standards

### Python Style Guide

- Follow PEP 8
- Maximum line length: 127 characters
- Use type hints
- Write docstrings for public functions and classes
- Use meaningful variable names

### Testing Requirements

- All new features must have tests
- Maintain >80% code coverage
- Include both unit and integration tests where appropriate

### Commit Messages

Follow conventional commits format:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes (formatting)
- `refactor:` Code refactoring
- `test:` Adding or updating tests
- `chore:` Maintenance tasks

Example:
```
feat(analyzer): add support for multi-chain analysis

- Implement Etherscan API integration
- Add BSC and Polygon support
- Update tests for new chains
```

## Architecture Overview

```
app/
├── config/          # Configuration management
├── security/        # Security analysis modules
├── ai/             # AI/ML modules
├── trading/        # Trading logic
├── multichain/     # Multi-chain support
├── dashboard/      # Dashboard and monitoring
├── infrastructure/ # Infrastructure utilities
└── main.py         # Application entry point
```

## Questions?

Feel free to open an issue for any questions or discussions.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
