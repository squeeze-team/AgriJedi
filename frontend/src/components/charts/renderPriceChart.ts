import * as d3 from 'd3';
import type { Crop, MultiPriceHistoryData } from '../../services/api';

interface SeriesStyle {
  key: Crop;
  label: string;
  color: string;
}

interface PricePoint {
  month: string;
  value: number;
}

const seriesStyles: SeriesStyle[] = [
  { key: 'wheat', label: 'Wheat', color: '#22d3ee' },
  { key: 'maize', label: 'Maize', color: '#e879f9' },
  { key: 'grape', label: 'Grapes', color: '#34d399' },
];

function shortMonthLabel(value: string) {
  const [year, month] = value.split('-');
  if (!year || !month) {
    return value;
  }
  return `${year.slice(2)}-${month}`;
}

export function renderPriceChart(container: HTMLDivElement, data: MultiPriceHistoryData) {
  container.replaceChildren();
  container.style.position = 'relative';

  const width = Math.max(320, container.clientWidth);
  const height = Math.max(220, container.clientHeight);
  const margin = { top: 40, right: 24, bottom: 56, left: 64 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  if (innerWidth <= 0 || innerHeight <= 0) {
    return;
  }

  const months = data.months;
  const series = seriesStyles.map((style) => ({
    ...style,
    points: months.map((month, index) => ({
      month,
      value: data.series[style.key][index],
    })) as PricePoint[],
  }));

  const allValues = series.flatMap((line) =>
    line.points
      .map((point) => point.value)
      .filter((value) => Number.isFinite(value)),
  );

  if (allValues.length === 0) {
    const message = document.createElement('div');
    message.className = 'h-full w-full grid place-items-center text-sm text-slate-500';
    message.textContent = 'No price data available.';
    container.appendChild(message);
    return;
  }

  const minPrice = d3.min(allValues) ?? 0;
  const maxPrice = d3.max(allValues) ?? 1;
  const padding = Math.max((maxPrice - minPrice) * 0.08, 4);

  const x = d3
    .scalePoint<string>()
    .domain(months)
    .range([margin.left, width - margin.right])
    .padding(0.25);

  const y = d3
    .scaleLinear()
    .domain([minPrice - padding, maxPrice + padding])
    .nice()
    .range([height - margin.bottom, margin.top]);

  const svg = d3
    .select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('role', 'img')
    .attr('aria-label', 'Commodity price history chart');

  const tooltip = d3
    .select(container)
    .append('div')
    .attr('class', 'chart-tooltip')
    .style('opacity', '0');

  svg
    .append('g')
    .attr('transform', `translate(${margin.left},0)`)
    .call(
      d3
        .axisLeft(y)
        .ticks(6)
        .tickSize(-innerWidth)
        .tickFormat(() => ''),
    )
    .call((axis) => axis.select('.domain').remove())
    .call((axis) => axis.selectAll('.tick line').attr('stroke', 'rgba(148,163,184,0.24)'));

  const line = d3
    .line<PricePoint>()
    .defined((point) => Number.isFinite(point.value))
    .x((point) => x(point.month) ?? margin.left)
    .y((point) => y(point.value));

  const dotsGroups: Array<d3.Selection<SVGCircleElement, PricePoint, SVGGElement, unknown>> = [];

  series.forEach((lineSeries) => {
    svg
      .append('path')
      .datum(lineSeries.points)
      .attr('fill', 'none')
      .attr('stroke', lineSeries.color)
      .attr('stroke-width', 2.2)
      .attr('d', line);

    const dots = svg
      .append('g')
      .selectAll('circle')
      .data(lineSeries.points.filter((point) => Number.isFinite(point.value)))
      .join('circle')
      .attr('cx', (point) => x(point.month) ?? margin.left)
      .attr('cy', (point) => y(point.value))
      .attr('r', 2.6)
      .attr('fill', lineSeries.color)
      .attr('stroke', '#e2e8f0')
      .attr('stroke-width', 0.7)
      .attr('data-series', lineSeries.key) as d3.Selection<SVGCircleElement, PricePoint, SVGGElement, unknown>;

    dotsGroups.push(dots);
  });

  const tickStep = Math.max(1, Math.ceil(months.length / 10));
  const xTickValues = months.filter((_month, idx, arr) => idx % tickStep === 0 || idx === arr.length - 1);

  svg
    .append('g')
    .attr('transform', `translate(0,${height - margin.bottom})`)
    .call(
      d3
        .axisBottom(x)
        .tickValues(xTickValues)
        .tickFormat((value) => shortMonthLabel(String(value))),
    )
    .call((axis) => axis.select('.domain').attr('stroke', 'rgba(148,163,184,0.35)'))
    .call((axis) => axis.selectAll('.tick line').attr('stroke', 'rgba(148,163,184,0.35)'))
    .call((axis) =>
      axis
        .selectAll<SVGTextElement, string>('.tick text')
        .attr('fill', '#cbd5e1')
        .attr('font-size', 11)
        .attr('transform', 'rotate(-42)')
        .style('text-anchor', 'end'),
    );

  svg
    .append('g')
    .attr('transform', `translate(${margin.left},0)`)
    .call(d3.axisLeft(y).ticks(6))
    .call((axis) => axis.select('.domain').attr('stroke', 'rgba(148,163,184,0.45)'))
    .call((axis) => axis.selectAll('.tick line').attr('stroke', 'rgba(148,163,184,0.35)'))
    .call((axis) => axis.selectAll('.tick text').attr('fill', '#cbd5e1').attr('font-size', 11));

  svg
    .append('text')
    .attr('x', 14)
    .attr('y', 14)
    .attr('fill', '#67e8f9')
    .attr('font-size', 12)
    .text(`USD / metric ton${data.isDemo ? ' (demo)' : ''}`);

  const legend = svg.append('g').attr('transform', `translate(${width / 2 - 120}, 8)`);
  series.forEach((lineSeries, index) => {
    const xOffset = index * 86;
    legend
      .append('line')
      .attr('x1', xOffset)
      .attr('x2', xOffset + 18)
      .attr('y1', 7)
      .attr('y2', 7)
      .attr('stroke', lineSeries.color)
      .attr('stroke-width', 2.5);
    legend
      .append('text')
      .attr('x', xOffset + 24)
      .attr('y', 11)
      .attr('font-size', 11)
      .attr('fill', '#e2e8f0')
      .text(lineSeries.label);
  });

  const hoverLine = svg
    .append('line')
    .attr('stroke', 'rgba(103,232,249,0.6)')
    .attr('stroke-width', 1.1)
    .attr('y1', margin.top)
    .attr('y2', height - margin.bottom)
    .style('display', 'none');

  const hoverDots = svg.append('g');
  seriesStyles.forEach((style) => {
    hoverDots
      .append('circle')
      .attr('r', 4.2)
      .attr('fill', style.color)
      .attr('stroke', '#f8fafc')
      .attr('stroke-width', 1.2)
      .attr('data-hover-series', style.key)
      .style('display', 'none');
  });

  const xCenters = months.map((month) => x(month) ?? margin.left);
  const hitboxes = months.map((month, index) => {
    const center = xCenters[index];
    const prev = index > 0 ? xCenters[index - 1] : center - 18;
    const next = index < xCenters.length - 1 ? xCenters[index + 1] : center + 18;
    const halfSpan = Math.max(10, (next - prev) / 2);
    return {
      month,
      index,
      x: center - halfSpan,
      width: halfSpan * 2,
    };
  });

  svg
    .append('g')
    .selectAll('rect')
    .data(hitboxes)
    .join('rect')
    .attr('x', (box) => box.x)
    .attr('y', margin.top)
    .attr('width', (box) => box.width)
    .attr('height', innerHeight)
    .attr('fill', 'transparent')
    .style('cursor', 'crosshair')
    .on('mouseenter', () => {
      hoverLine.style('display', 'block');
      hoverDots.selectAll('circle').style('display', 'block');
      tooltip.style('opacity', '1');
    })
    .on('mousemove', (event, box) => {
      const center = xCenters[box.index];
      hoverLine.attr('x1', center).attr('x2', center);

      dotsGroups.forEach((group) => {
        group.attr('r', (point) => (point.month === box.month ? 4 : 2.6));
      });

      const lines: string[] = [];
      series.forEach((lineSeries) => {
        const point = lineSeries.points[box.index];
        if (!point || !Number.isFinite(point.value)) {
          return;
        }
        hoverDots
          .selectAll<SVGCircleElement, unknown>('circle')
          .filter(function () {
            return this.getAttribute('data-hover-series') === lineSeries.key;
          })
          .attr('cx', center)
          .attr('cy', y(point.value));

        lines.push(
          `<div><span style="display:inline-block;width:8px;height:8px;border-radius:999px;background:${lineSeries.color};margin-right:6px;"></span>${lineSeries.label}: ${point.value.toFixed(1)}</div>`,
        );
      });

      const [pointerX, pointerY] = d3.pointer(event, container);
      const tooltipLeft = Math.max(8, Math.min(width - 190, pointerX + 14));
      const tooltipTop = Math.max(8, Math.min(height - 88, pointerY - 16));

      tooltip
        .style('left', `${tooltipLeft}px`)
        .style('top', `${tooltipTop}px`)
        .html(`<div class="chart-tooltip-title">${box.month}</div>${lines.join('')}`);
    })
    .on('mouseleave', () => {
      hoverLine.style('display', 'none');
      hoverDots.selectAll('circle').style('display', 'none');
      tooltip.style('opacity', '0');
      dotsGroups.forEach((group) => group.attr('r', 2.6));
    });
}
