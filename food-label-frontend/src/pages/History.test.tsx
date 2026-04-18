import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { apiDelete, apiGet } from '@/api/client';
import type { ApiResponse, PageResponse } from '@/types/api';
import History from './History';

vi.mock('@/api/client', () => ({
  apiDelete: vi.fn(),
  apiGet: vi.fn(),
}));

const apiDeleteMock = vi.mocked(apiDelete);
const apiGetMock = vi.mocked(apiGet);

interface ReportListItem {
  report_id: string;
  task_id: string;
  score: number;
  summary: string;
  image_url: string;
  created_at: string;
}

function okResponse<T>(data: T): ApiResponse<T> {
  return {
    code: 0,
    message: 'ok',
    data,
  };
}

function pageResponse(
  items: ReportListItem[],
  {
    total,
    page,
    pageSize = 10,
  }: {
    total: number;
    page: number;
    pageSize?: number;
  },
): ApiResponse<PageResponse<ReportListItem>> {
  return okResponse({
    items,
    total,
    page,
    page_size: pageSize,
    total_pages: Math.max(1, Math.ceil(total / pageSize)),
  });
}

function renderHistory() {
  render(
    <MemoryRouter>
      <History />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('History', () => {
  it('reloads the current page after deletion and accepts the server-corrected page number', async () => {
    apiGetMock
      .mockResolvedValueOnce(
        pageResponse(
          [
            {
              report_id: 'report-11',
              task_id: 'task-11',
              score: 72,
              summary: 'summary page 2',
              image_url: '',
              created_at: '2026-04-19T10:00:00Z',
            },
          ],
          {
            total: 11,
            page: 2,
          },
        ),
      )
      .mockResolvedValueOnce(
        pageResponse(
          [
            {
              report_id: 'report-10',
              task_id: 'task-10',
              score: 81,
              summary: 'summary page 1',
              image_url: '',
              created_at: '2026-04-19T09:00:00Z',
            },
          ],
          {
            total: 10,
            page: 1,
          },
        ),
      );
    apiDeleteMock.mockResolvedValue(okResponse(null));

    renderHistory();

    await waitFor(() => {
      expect(screen.getByText('summary page 2')).toBeTruthy();
    });

    fireEvent.click(screen.getAllByRole('button', { name: /鍒犻櫎|删除/ })[0]!);

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /鍒犻櫎|删除/ })).toHaveLength(2);
    });

    fireEvent.click(screen.getAllByRole('button', { name: /鍒犻櫎|删除/ })[1]!);

    await waitFor(() => {
      expect(apiGetMock).toHaveBeenCalledTimes(2);
      expect(screen.getByText('summary page 1')).toBeTruthy();
    });

    expect(apiGetMock).toHaveBeenNthCalledWith(1, '/reports?page=1&page_size=10');
    expect(apiGetMock).toHaveBeenNthCalledWith(2, '/reports?page=2&page_size=10');
    expect(screen.queryByText('summary page 2')).toBeNull();
    expect(apiDeleteMock).toHaveBeenCalledWith('/reports/report-11');
  });
});
