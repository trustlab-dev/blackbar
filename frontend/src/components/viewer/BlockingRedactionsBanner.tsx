// frontend/src/components/viewer/BlockingRedactionsBanner.tsx
//
// Lists the redactions that block export and release, each with the reason
// the server gives (metadata `unresolved_redactions` / `review_required`,
// backend/src/documents/routes.py; reasons from UNRESOLVED_REASONS in
// backend/src/utils/redaction_records.py). Approve/Reject is offered where
// the approve route can resolve the record (`approvable`); Delete where the
// fix is to delete and re-add the box (no usable geometry, legacy
// coordinates on a rotated page).
import React from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Collapse from '@mui/material/Collapse';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Typography from '@mui/material/Typography';
import {
  canDeleteToResolve,
  describeBlockingStatus,
  unresolvedReasonLabel,
  UnresolvedRedaction,
} from '../../utils/redactionStatus';

export interface BlockingRedaction {
  id?: string;
  page: number;
  status?: string;
  type?: string;
  categoryName?: string;
  notes?: string;
  /** Why it blocks (server-provided, or the client rule as a fallback). */
  review: UnresolvedRedaction;
}

export const LEGACY_NO_ID_HINT =
  'This older redaction has no ID, so it is read-only here. Ask an administrator to migrate it.';

export interface BlockingActions {
  approve: boolean;
  delete: boolean;
  /** The reason, or why nothing can be done here. */
  hint: string;
}

/** What the reviewer can do about one blocking redaction. */
export function blockingActions(redaction: BlockingRedaction): BlockingActions {
  if (!redaction.id) return { approve: false, delete: false, hint: LEGACY_NO_ID_HINT };
  const reason = String(redaction.review.reason);
  return {
    approve: redaction.review.approvable,
    delete: canDeleteToResolve(reason),
    hint: unresolvedReasonLabel(reason),
  };
}

interface Props {
  redactions: BlockingRedaction[];
  expanded: boolean;
  onToggle: () => void;
  onApprove: (redaction: BlockingRedaction) => void;
  onReject: (redaction: BlockingRedaction) => void;
  onDelete: (redaction: BlockingRedaction) => void;
  onGoTo: (redaction: BlockingRedaction) => void;
  busyId?: string | null;
}

const BlockingRedactionsBanner: React.FC<Props> = ({
  redactions,
  expanded,
  onToggle,
  onApprove,
  onReject,
  onDelete,
  onGoTo,
  busyId,
}) => {
  if (redactions.length === 0) return null;
  const count = redactions.length;

  return (
    <Box data-testid="blocking-redactions" sx={{ borderBottom: '1px solid var(--border-default)' }}>
      <Alert
        severity="warning"
        sx={{ borderRadius: 0, py: 0 }}
        action={
          <Button color="inherit" size="small" onClick={onToggle}>
            {expanded ? 'Hide' : 'Review'}
          </Button>
        }
      >
        <strong>
          {count} redaction{count !== 1 ? 's' : ''} awaiting review.
        </strong>{' '}
        Only approved redactions are applied. Export and release are blocked until each one is
        resolved.
      </Alert>
      <Collapse in={expanded} unmountOnExit>
        <List dense sx={{ maxHeight: 220, overflow: 'auto', py: 0, bgcolor: 'var(--bg-secondary, #fff)' }}>
          {redactions.map((redaction, index) => {
            const actions = blockingActions(redaction);
            const busy = Boolean(redaction.id) && busyId === redaction.id;
            const buttonCount = 1 + (actions.approve ? 2 : 0) + (actions.delete ? 1 : 0);
            return (
              <ListItem
                key={redaction.id ?? `legacy-${index}`}
                divider
                secondaryAction={
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button size="small" onClick={() => onGoTo(redaction)}>
                      Show
                    </Button>
                    {actions.approve && (
                      <>
                        <Button
                          size="small"
                          variant="contained"
                          color="success"
                          disabled={busy}
                          onClick={() => onApprove(redaction)}
                        >
                          Approve
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          color="error"
                          disabled={busy}
                          onClick={() => onReject(redaction)}
                        >
                          Reject
                        </Button>
                      </>
                    )}
                    {actions.delete && (
                      <Button
                        size="small"
                        variant="outlined"
                        color="error"
                        disabled={busy}
                        onClick={() => onDelete(redaction)}
                      >
                        Delete
                      </Button>
                    )}
                  </Box>
                }
              >
                <ListItemText
                  sx={{ pr: buttonCount * 10 }}
                  primary={`Page ${redaction.page} · ${redaction.categoryName || 'No category'} · ${describeBlockingStatus(redaction)}`}
                  secondary={
                    <>
                      {redaction.notes && (
                        <Typography component="span" variant="caption" sx={{ display: 'block' }}>
                          {redaction.notes}
                        </Typography>
                      )}
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                        {actions.hint}
                      </Typography>
                    </>
                  }
                />
              </ListItem>
            );
          })}
        </List>
      </Collapse>
    </Box>
  );
};

export default BlockingRedactionsBanner;
