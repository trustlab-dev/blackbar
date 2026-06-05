// frontend/src/components/viewer/CommentsDrawer.tsx
import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Drawer from '@mui/material/Drawer';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Divider from '@mui/material/Divider';
import Avatar from '@mui/material/Avatar';
import Close from '@mui/icons-material/Close';
import Send from '@mui/icons-material/Send';
import api from '../../api/client';

interface Comment {
    id: string;
    content: string;
    user_id: string;
    username: string;
    created_at: string;
}

interface Props {
    open: boolean;
    onClose: () => void;
    documentId: string;
}

const CommentsDrawer: React.FC<Props> = ({ open, onClose, documentId }) => {
    const [comments, setComments] = useState<Comment[]>([]);
    const [loading, setLoading] = useState(false);
    const [errorMessage, setErrorMessage] = useState('');
    const [newComment, setNewComment] = useState('');
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (open && documentId) {
            fetchComments();
        }
    }, [open, documentId]);

    const fetchComments = async () => {
        setLoading(true);
        setErrorMessage('');
        try {
            const response = await api.get(`/documents/${documentId}/comments`);
            setComments(response.data.comments || response.data || []);
        } catch (error: any) {
            // Document comments endpoint not yet implemented — show empty state
            if (error.response?.status === 404 || error.response?.status === 405) {
                setComments([]);
            } else {
                console.error('Error fetching comments:', error);
                setErrorMessage(error.response?.data?.detail || 'Failed to load comments');
            }
        } finally {
            setLoading(false);
        }
    };

    const handleSubmit = async () => {
        if (!newComment.trim()) return;

        setSubmitting(true);
        try {
            await api.post(`/documents/${documentId}/comments`, {
                content: newComment.trim()
            });
            setNewComment('');
            fetchComments();
        } catch (error: any) {
            console.error('Error adding comment:', error);
            setErrorMessage('Document comments are not yet available');
        } finally {
            setSubmitting(false);
        }
    };

    const formatTimestamp = (timestamp: string): string => {
        try {
            const isoTimestamp = timestamp.endsWith('Z') ? timestamp : timestamp + 'Z';
            const date = new Date(isoTimestamp);
            return date.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch (e) {
            return timestamp;
        }
    };

    const getInitials = (name: string): string => {
        return name.split(' ')
            .map(word => word[0])
            .slice(0, 2)
            .join('')
            .toUpperCase() || '?';
    };

    return (
        <Drawer
            anchor="right"
            open={open}
            onClose={onClose}
            variant="persistent"
            sx={{
                '& .MuiDrawer-paper': {
                    width: 400,
                    right: '60px',
                    height: '100%',
                    boxShadow: 3,
                    position: 'absolute',
                    zIndex: 1200
                }
            }}
            ModalProps={{
                keepMounted: true,
                BackdropProps: {
                    invisible: true
                }
            }}
        >
            <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                {/* Header */}
                <Box sx={{ p: 2, borderBottom: '1px solid var(--border-default)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Typography variant="h6">Comments</Typography>
                    <IconButton size="small" onClick={onClose}>
                        <Close />
                    </IconButton>
                </Box>

                {/* Error Message */}
                {errorMessage && (
                    <Alert severity="error" onClose={() => setErrorMessage('')} sx={{ m: 2 }}>
                        {errorMessage}
                    </Alert>
                )}

                {/* Comments List */}
                <Box sx={{ flex: 1, overflow: 'auto' }}>
                    {loading ? (
                        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                            <CircularProgress />
                        </Box>
                    ) : comments.length === 0 ? (
                        <Alert severity="info" sx={{ m: 2 }}>No comments yet. Be the first to comment!</Alert>
                    ) : (
                        <List sx={{ p: 0 }}>
                            {comments.map((comment, index) => (
                                <Box key={comment.id || index}>
                                    <ListItem alignItems="flex-start" sx={{ py: 2, px: 2 }}>
                                        <Avatar
                                            sx={{
                                                width: 36,
                                                height: 36,
                                                bgcolor: '#3b82f6',
                                                color: 'white',
                                                mr: 2,
                                                fontSize: '14px'
                                            }}
                                        >
                                            {getInitials(comment.username || 'Unknown')}
                                        </Avatar>
                                        <ListItemText
                                            primary={
                                                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                                                        {comment.username || 'Unknown'}
                                                    </Typography>
                                                    <Typography variant="caption" color="text.secondary">
                                                        {formatTimestamp(comment.created_at)}
                                                    </Typography>
                                                </Box>
                                            }
                                            secondary={
                                                <Typography variant="body2" color="text.primary" sx={{ mt: 0.5 }}>
                                                    {comment.content}
                                                </Typography>
                                            }
                                        />
                                    </ListItem>
                                    {index < comments.length - 1 && <Divider component="li" />}
                                </Box>
                            ))}
                        </List>
                    )}
                </Box>

                {/* Add Comment Input */}
                <Box sx={{ p: 2, borderTop: '1px solid var(--border-default)' }}>
                    <TextField
                        fullWidth
                        multiline
                        rows={2}
                        placeholder="Add a comment..."
                        value={newComment}
                        onChange={(e) => setNewComment(e.target.value)}
                        size="small"
                        sx={{ mb: 1 }}
                    />
                    <Button
                        fullWidth
                        variant="contained"
                        startIcon={<Send />}
                        onClick={handleSubmit}
                        disabled={!newComment.trim() || submitting}
                    >
                        {submitting ? 'Sending...' : 'Add Comment'}
                    </Button>
                </Box>
            </Box>
        </Drawer>
    );
};

export default CommentsDrawer;
