# 📐 24-Hour Global Cost Optimization — Mathematical Formulation

**Project:** GridWise LLM — Smart Campus Energy Optimization  
**Team:** SUST Crusade (BUP CSE Fest 2026)  
**Solver Engine:** PuLP with COIN-OR CBC (Linear Programming)

---

## 🎯 1. Objective Function (মিনিমাম কস্ট ফাংশন)

Minimize total electricity purchase cost over 24 hours with a micro-regularization term ($\epsilon = 10^{-5}$) to eliminate dummy battery cycles:

$$\min \sum_{t=0}^{23} \left( \text{Tariff}_t \times \text{Grid}_t \right) + \epsilon \sum_{t=0}^{23} \left( \text{Charge}_t + \text{Discharge}_t \right)$$

Where:
- $\text{Tariff}_t$: Electricity price in BDT/kWh at hour $t \in [0, 23]$
- $\text{Grid}_t$: Electricity imported from the utility grid (kWh)
- $\epsilon = 10^{-5}$: Prevents simultaneous charging and discharging during tariff ties

---

## ⚡ 2. Core Physical Constraints (বাধ্যতামূলক ফিজিক্যাল নিয়ম)

### (A) Hourly Energy Balance (প্রতি ঘণ্টার শক্তি সমতা)
At every single hour $t$, campus demand must be satisfied exactly:
$$\text{Demand}_t = \text{Grid}_t + \text{SolarUsed}_t + \text{Discharge}_t - \text{Charge}_t$$

### (B) Usable Solar Availability
Solar used cannot exceed the directive-adjusted usable forecast:
$$0 \le \text{SolarUsed}_t \le \alpha_t \times \text{SolarForecast}_t$$
*(where $\alpha_t \in (0, 1]$ is the active solar reduction factor, e.g. $\alpha_t = 0.25$ during cleaning)*

### (C) Battery Dynamics & State of Charge (SoC)
Energy stored at the end of hour $t$:
$$E_t = E_{t-1} + \text{Charge}_t - \text{Discharge}_t \quad (\text{with } E_{-1} = E_{\text{initial}})$$

### (D) Capacity & C-Rate Limits
$$E_{\min, t} \le E_t \le E_{\text{capacity}}$$
$$0 \le \text{Charge}_t \le C_{\max}$$
$$0 \le \text{Discharge}_t \le D_{\max}$$

---

## 🔄 3. Battery Neutrality Constraint (সবচেয়ে গুরুত্বপূর্ণ শর্ত)

To ensure sustainable, perpetual campus operations without battery depletion:
$$E_{23} = E_{\text{initial}}$$
*(The battery energy at the end of the 24-hour cycle MUST equal its starting energy).*

---

## 🛡️ 4. Dynamic Operator Directive Bounds (এলএলএম ডিরেক্টিভ)

When human operator directives are active for window $t \in \mathcal{H}_{\text{window}}$:
- **`no_charge_window`**: $\text{Charge}_t = 0$
- **`no_discharge_window`**: $\text{Discharge}_t = 0$
- **`minimum_battery_reserve`**: $E_t \ge \text{ReserveLimit}$
- **`max_grid_window`**: $\text{Grid}_t \le \text{MaxGridLimit}$
- **`solar_reduction`**: Usable solar capped by $\alpha_t \times \text{SolarForecast}_t$

---

## 📊 Summary
- **Decision Variables per Day:** 96 continuous linear variables ($24 \times [\text{Grid}, \text{SolarUsed}, \text{Charge}, \text{Discharge}]$).
- **Optimality:** Guaranteed **Global Optimum** within $< 0.05$ seconds using CBC simplex/interior-point algorithms.
