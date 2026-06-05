import React from 'react';

interface FeatureDisabledProps {
  featureName: string;
}

const FeatureDisabled: React.FC<FeatureDisabledProps> = ({ featureName }) => {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '60vh',
      padding: '40px',
      textAlign: 'center'
    }}>
      <div style={{
        fontSize: '64px',
        marginBottom: '20px',
        opacity: 0.3
      }}>
        🚫
      </div>
      <h1 style={{
        fontSize: '28px',
        fontWeight: 600,
        marginBottom: '12px',
        color: '#24292e'
      }}>
        Feature Not Available
      </h1>
      <p style={{
        fontSize: '16px',
        color: '#586069',
        marginBottom: '30px',
        maxWidth: '500px'
      }}>
        {featureName} has been disabled by the administrator.
      </p>
      <a
        href="/login"
        style={{
          padding: '10px 20px',
          backgroundColor: '#0366d6',
          color: 'white',
          textDecoration: 'none',
          borderRadius: '6px',
          fontSize: '14px',
          fontWeight: 600
        }}
      >
        Go to Login
      </a>
    </div>
  );
};

export default FeatureDisabled;
