import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { apiGet } from '@/api/client';
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
