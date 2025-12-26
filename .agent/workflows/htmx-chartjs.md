---
description: HTMX and Chart.js integration best practices
---

# HTMX + Chart.js Integration Rules

## Problem
When using HTMX to swap page content that contains Chart.js charts, the charts may render incorrectly (cut off, wrong size) because:

1. The `htmx:afterSwap` event fires before the DOM is fully rendered
2. Chart.js calculates canvas size based on container dimensions at initialization time
3. During HTMX swap, containers may temporarily have zero height

## Solution

### 1. Always add min-height to chart containers
```html
<div id="chart-container" style="height: 300px; min-height: 300px; position: relative; width: 100%;">
    <canvas id="myChart"></canvas>
</div>
```

### 2. Add delay to chart initialization after HTMX swap
```javascript
// Initial load - no delay needed
document.addEventListener('DOMContentLoaded', initChart);

// After HTMX swap - add delay to ensure DOM is fully rendered
document.body.addEventListener('htmx:afterSwap', function() {
    setTimeout(initChart, 100);
});
```

### 3. Always destroy existing chart before re-creating
```javascript
function initChart() {
    // Destroy existing chart to prevent memory leaks
    if (window.myChart) {
        window.myChart.destroy();
    }
    
    // Create new chart
    window.myChart = new Chart(ctx, { ... });
}
```

## Additional Tips
- Use `maintainAspectRatio: false` in Chart.js options when using fixed container height
- Add `width: 100%` to container for responsive charts
- Consider using `htmx:afterSettle` instead of `htmx:afterSwap` if issues persist
