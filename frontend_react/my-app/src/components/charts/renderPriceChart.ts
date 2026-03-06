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
  { key: 'wheat', label: 'Wheat', color: '#16a34a' },
  { key: 'maize', label: 'Maize', color: '#2563eb' },
  { key: 'grape', label: 'Grapes', color: '#9333ea' },
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
    .call((axis) => axis.selectAll('.tick line').attr('stroke', '#e2e8f0'));

  const line = d3
    .line<PricePoint>()
    .defined((point) => Number.isFinite(point.value))
    .x((point) => x(point.month) ?? margin.left)
    .y((point) => y(point.value));

  series.forEach((lineSeries) => {
    svg
      .append('path')
      .datum(lineSeries.points)
      .attr('fill', 'none')
      .attr('stroke', lineSeries.color)
      .attr('stroke-width', 2.2)
      .attr('d', line);
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
    .call((axis) => axis.select('.domain').attr('stroke', '#cbd5e1'))
    .call((axis) => axis.selectAll('.tick line').attr('stroke', '#cbd5e1'))
    .call((axis) =>
      axis
        .selectAll<SVGTextElement, string>('.tick text')
        .attr('fill', '#475569')
        .attr('font-size', 11)
        .attr('transform', 'rotate(-42)')
        .style('text-anchor', 'end'),
    );

  svg
    .append('g')
    .attr('transform', `translate(${margin.left},0)`)
    .call(d3.axisLeft(y).ticks(6))
    .call((axis) => axis.select('.domain').attr('stroke', '#94a3b8'))
    .call((axis) => axis.selectAll('.tick line').attr('stroke', '#cbd5e1'))
    .call((axis) => axis.selectAll('.tick text').attr('fill', '#475569').attr('font-size', 11));

  svg
    .append('text')
    .attr('x', 14)
    .attr('y', 14)
    .attr('fill', '#475569')
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
      .attr('fill', '#334155')
      .text(lineSeries.label);
  });
}
