import * as d3 from 'd3';
import type { WeatherData } from '../../services/api';

interface WeatherPoint {
  month: string;
  precip: number;
  temp: number;
}

function shortMonthLabel(value: string) {
  const [year, month] = value.split('-');
  if (!year || !month) {
    return value;
  }
  return `${year.slice(2)}-${month}`;
}

export function renderWeatherChart(container: HTMLDivElement, data: WeatherData) {
  container.replaceChildren();

  const width = Math.max(320, container.clientWidth);
  const height = Math.max(220, container.clientHeight);
  const margin = { top: 44, right: 56, bottom: 56, left: 56 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  if (innerWidth <= 0 || innerHeight <= 0) {
    return;
  }

  const points: WeatherPoint[] = data.months.map((month, idx) => ({
    month,
    precip: Number.isFinite(data.PRECTOTCORR[idx]) ? data.PRECTOTCORR[idx] : 0,
    temp: Number.isFinite(data.T2M[idx]) ? data.T2M[idx] : 0,
  }));

  const x = d3
    .scaleBand<string>()
    .domain(points.map((point) => point.month))
    .range([margin.left, width - margin.right])
    .padding(0.18);

  const maxPrecip = d3.max(points, (point) => point.precip) ?? 0;
  const minTemp = d3.min(points, (point) => point.temp) ?? 0;
  const maxTemp = d3.max(points, (point) => point.temp) ?? 0;

  const yLeft = d3
    .scaleLinear()
    .domain([0, Math.max(10, maxPrecip * 1.15)])
    .nice()
    .range([height - margin.bottom, margin.top]);

  const yRight = d3
    .scaleLinear()
    .domain([Math.min(0, minTemp - 2), maxTemp + 2])
    .nice()
    .range([height - margin.bottom, margin.top]);

  const svg = d3
    .select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('role', 'img')
    .attr('aria-label', 'Weather chart for precipitation and temperature');

  svg
    .append('g')
    .attr('transform', `translate(${margin.left},0)`)
    .call(
      d3
        .axisLeft(yLeft)
        .ticks(5)
        .tickSize(-innerWidth)
        .tickFormat(() => ''),
    )
    .call((axis) => axis.select('.domain').remove())
    .call((axis) => axis.selectAll('.tick line').attr('stroke', '#e2e8f0'));

  svg
    .append('g')
    .selectAll('rect')
    .data(points)
    .join('rect')
    .attr('x', (point) => x(point.month) ?? 0)
    .attr('y', (point) => yLeft(point.precip))
    .attr('width', x.bandwidth())
    .attr('height', (point) => Math.max(0, height - margin.bottom - yLeft(point.precip)))
    .attr('fill', '#7ea4f3')
    .attr('opacity', 0.8);

  const line = d3
    .line<WeatherPoint>()
    .defined((point) => Number.isFinite(point.temp))
    .x((point) => (x(point.month) ?? 0) + x.bandwidth() / 2)
    .y((point) => yRight(point.temp));

  svg
    .append('path')
    .datum(points)
    .attr('fill', 'none')
    .attr('stroke', '#ea580c')
    .attr('stroke-width', 2.5)
    .attr('d', line);

  const tickStep = Math.max(1, Math.ceil(points.length / 8));
  const xTickValues = points
    .map((point) => point.month)
    .filter((_month, idx, arr) => idx % tickStep === 0 || idx === arr.length - 1);

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
    .call(d3.axisLeft(yLeft).ticks(5))
    .call((axis) => axis.select('.domain').attr('stroke', '#94a3b8'))
    .call((axis) => axis.selectAll('.tick line').attr('stroke', '#cbd5e1'))
    .call((axis) => axis.selectAll('.tick text').attr('fill', '#475569').attr('font-size', 11));

  svg
    .append('g')
    .attr('transform', `translate(${width - margin.right},0)`)
    .call(d3.axisRight(yRight).ticks(5))
    .call((axis) => axis.select('.domain').attr('stroke', '#94a3b8'))
    .call((axis) => axis.selectAll('.tick line').attr('stroke', '#cbd5e1'))
    .call((axis) => axis.selectAll('.tick text').attr('fill', '#475569').attr('font-size', 11));

  svg
    .append('text')
    .attr('x', margin.left)
    .attr('y', 16)
    .attr('fill', '#475569')
    .attr('font-size', 12)
    .text('Precipitation (mm)');

  svg
    .append('text')
    .attr('x', width - margin.right)
    .attr('y', 16)
    .attr('text-anchor', 'end')
    .attr('fill', '#475569')
    .attr('font-size', 12)
    .text('Temp Mean (degC)');

  const legend = svg.append('g').attr('transform', `translate(${width / 2 - 110}, 8)`);
  legend.append('rect').attr('x', 0).attr('y', 2).attr('width', 18).attr('height', 10).attr('fill', '#7ea4f3');
  legend
    .append('text')
    .attr('x', 24)
    .attr('y', 11)
    .attr('font-size', 11)
    .attr('fill', '#334155')
    .text('Precipitation');
  legend
    .append('line')
    .attr('x1', 120)
    .attr('x2', 140)
    .attr('y1', 7)
    .attr('y2', 7)
    .attr('stroke', '#ea580c')
    .attr('stroke-width', 2.5);
  legend
    .append('text')
    .attr('x', 146)
    .attr('y', 11)
    .attr('font-size', 11)
    .attr('fill', '#334155')
    .text('Temp Mean');
}
