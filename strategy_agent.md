# Strategy Execution & Management Specifications

This document outlines the requirements for automating the entry and management of **Vertical Credit Spreads** and **Iron Condors**.

---

## 🏗️ General Entry Guidelines
These guidelines apply to both Vertical Credit Spreads and Iron Condors.

- **IVR Requirement**: Symbol must have an **IVR above 25%**.
- **Timeframe (DTE)**: 
  - Target **45 Days to Expiration (DTE)** or the nearest Monthly expiration.
  - **Exclude all Weekly expirations.**
- **Strike Selection**: Identify the strike nearest to **30 Delta**.
- **Spread Width**:
  - If strikes are $1 wide: Minimum width is **$3**.
  - If strikes are $5 wide: Width must NOT exceed **$5**.
- **Credit Requirement**: Collected credit must be at least **1/3rd of the spread width**.

---

## 📈 Strategies

### 1. Vertical Credit Spreads
- Follows all [General Entry Guidelines](#-general-entry-guidelines).

### 2. Iron Condors
- Follows all [General Entry Guidelines](#-general-entry-guidelines) for both the Put and Call sides.

---

## 🛡️ Trade Management & Exit Logic

Positions must be managed based on profit targets or time-based stops.

- **Profit Target**: Auto-close at **50% of the total credit received**.
- **Time-based Stop**: 
  - Close the trade at **21 Days to Expiration (DTE)** if the profit target hasn't been hit.
  - Close **regardless** of overall trade profit or loss.