import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { apiGet } from '@/api/client';
import { getAnalysisProgress } from '@/lib/analysis-progress';
import Analyzing from './Analyzing';

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
}));

const apiGetMock = vi.mocked(apiGet);

function renderAnalyzing(taskId = 'task-1') {
  render(
    <MemoryRouter initialEntries={[`/analyzing/${taskId}`]}>
      <Routes>
        <Route path="/analyzing/:taskId" element={<Analyzing />} />
        <Route path="/" element={<div>home</div>} />
        <Route path="/reports/:reportId" element={<div>report</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe('Analyzing', () => {
  it('derives a smooth estimated progress from task status and elapsed time', () => {
    expect(getAnalysisProgress(null, Date.parse('2026-04-18T10:00:00Z'))).toMatchObject({
      percent: 6,
      headline: '初始化分析引擎',
    });

    expect(
      getAnalysisProgress(
        {
          task_id: 'task-1',
          status: 'queued',
          progress_message: '任务排队中，请稍候...',
          created_at: '2026-04-18T10:00:00Z',
          report_id: null,
          error_message: null,
        },
        Date.parse('2026-04-18T10:00:10Z'),
      ),
    ).toMatchObject({
      percent: 10,
      headline: '任务排队中',
    });

    expect(
      getAnalysisProgress(
        {
          task_id: 'task-1',
          status: 'processing',
          progress_message: '正在分析食品标签...',
          created_at: '2026-04-18T10:00:10Z',
          report_id: null,
          error_message: null,
        },
        Date.parse('2026-04-18T10:00:32Z'),
      ),
    ).toMatchObject({
      percent: 48,
      activeStepIndex: 2,
      headline: '营养与配料结构化',
    });

    expect(
      getAnalysisProgress(
        {
          task_id: 'task-1',
          status: 'completed',
          progress_message: '分析完成',
          created_at: '2026-04-18T10:00:00Z',
          report_id: 'report-1',
          error_message: null,
        },
        Date.parse('2026-04-18T10:00:32Z'),
      ),
    ).toMatchObject({
      percent: 100,
      headline: '分析完成',
    });
  });

  it('renders the expanded analysis step timeline while processing', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-18T10:00:32Z'));
    apiGetMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        task_id: 'task-1',
        status: 'processing',
        progress_message: '正在分析食品标签...',
        created_at: '2026-04-18T10:00:10Z',
        report_id: null,
        error_message: null,
      },
    });

    renderAnalyzing();

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText('AI 正在分析食品标签')).toBeTruthy();
    expect(screen.getByText('OCR 文字与营养表识别')).toBeTruthy();
    expect(screen.getAllByText('营养与配料结构化').length).toBeGreaterThan(0);
    expect(screen.getByText('风险检索与规则评分')).toBeTruthy();
    expect(screen.getByText('生成健康报告')).toBeTruthy();
    expect(screen.getByText('48%')).toBeTruthy();
  });

  it('shows an error after repeated polling failures instead of retrying forever', async () => {
    vi.useFakeTimers();
    apiGetMock.mockRejectedValue(new Error('network down'));

    renderAnalyzing();

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(apiGetMock).toHaveBeenCalledTimes(3);
    expect(screen.getByText('network down')).toBeTruthy();
  });

  it('shows a timeout error when the analysis task exceeds the maximum wait time', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-18T10:10:01Z'));
    apiGetMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        task_id: 'task-1',
        status: 'processing',
        progress_message: '正在分析',
        created_at: '2026-04-18T10:00:00Z',
        report_id: null,
        error_message: null,
      },
    });

    renderAnalyzing();

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(screen.getByText(/OCR\/LLM/)).toBeTruthy();
  });
});
