import React, { Component, ReactNode } from 'react';
import { captureError } from '../utils/telemetry';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
  errorInfo?: string;
}

class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: any) {
    captureError(error, { componentStack: errorInfo?.componentStack });

    this.setState({
      hasError: true,
      error,
      errorInfo: errorInfo?.componentStack || '' 
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '40px',
          textAlign: 'center',
          maxWidth: '600px',
          margin: '100px auto',
          backgroundColor: '#fff',
          borderRadius: '8px',
          boxShadow: '0 2px 10px rgba(0,0,0,0.1)'
        }}>
          <h1 style={{ color: '#d73a49', marginBottom: '20px' }}>
            Something went wrong
          </h1>
          <p style={{ color: '#586069', marginBottom: '30px' }}>
            We're sorry, but something unexpected happened. 
            Please try refreshing the page or contact support if the problem persists.
          </p>
          
          {import.meta.env.DEV && this.state.error && (
            <details style={{
              textAlign: 'left',
              backgroundColor: '#f6f8fa',
              padding: '15px',
              borderRadius: '6px',
              marginTop: '20px',
              border: '1px solid #d1d5da'
            }}>
              <summary style={{ cursor: 'pointer', fontWeight: 'bold', marginBottom: '10px' }}>
                Error Details
              </summary>
              <pre style={{
                fontSize: '12px',
                overflow: 'auto',
                color: '#d73a49'
              }}>
                {this.state.error.toString()}
                {this.state.errorInfo && '\n' + this.state.errorInfo}
              </pre>
            </details>
          )}
          
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: '20px',
              padding: '10px 20px',
              backgroundColor: '#0366d6',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '600'
            }}
          >
            Refresh Page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
