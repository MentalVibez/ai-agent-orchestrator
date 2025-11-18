"""Unit tests for Retry Logic."""

import pytest
from unittest.mock import AsyncMock, patch
from app.core.retry import retry_async, RetryConfig, retryable


@pytest.mark.unit
class TestRetryConfig:
    """Test cases for RetryConfig."""
    
    def test_initialization_defaults(self):
        """Test RetryConfig with default values."""
        config = RetryConfig()
        
        assert config.max_attempts == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
        assert config.retryable_exceptions == (Exception,)
    
    def test_initialization_custom(self):
        """Test RetryConfig with custom values."""
        config = RetryConfig(
            max_attempts=5,
            initial_delay=0.5,
            max_delay=30.0,
            exponential_base=3.0,
            retryable_exceptions=(ValueError, KeyError)
        )
        
        assert config.max_attempts == 5
        assert config.initial_delay == 0.5
        assert config.max_delay == 30.0
        assert config.exponential_base == 3.0
        assert config.retryable_exceptions == (ValueError, KeyError)


@pytest.mark.unit
class TestRetryAsync:
    """Test cases for retry_async function."""
    
    @pytest.mark.asyncio
    async def test_retry_success_first_attempt(self):
        """Test retry succeeds on first attempt."""
        func = AsyncMock(return_value="success")
        
        result = await retry_async(func)
        
        assert result == "success"
        assert func.call_count == 1
    
    @pytest.mark.asyncio
    async def test_retry_success_after_retries(self):
        """Test retry succeeds after some failures."""
        func = AsyncMock(side_effect=[ValueError("Error"), ValueError("Error"), "success"])
        config = RetryConfig(max_attempts=3, retryable_exceptions=(ValueError,))
        
        result = await retry_async(func, config=config)
        
        assert result == "success"
        assert func.call_count == 3
    
    @pytest.mark.asyncio
    async def test_retry_all_attempts_fail(self):
        """Test retry fails after all attempts."""
        func = AsyncMock(side_effect=ValueError("Error"))
        config = RetryConfig(max_attempts=2, retryable_exceptions=(ValueError,))
        
        with pytest.raises(ValueError):
            await retry_async(func, config=config)
        
        assert func.call_count == 2
    
    @pytest.mark.asyncio
    async def test_retry_non_retryable_exception(self):
        """Test retry doesn't retry on non-retryable exceptions."""
        func = AsyncMock(side_effect=KeyError("Error"))
        config = RetryConfig(max_attempts=3, retryable_exceptions=(ValueError,))
        
        with pytest.raises(KeyError):
            await retry_async(func, config=config)
        
        assert func.call_count == 1
    
    @pytest.mark.asyncio
    @patch('asyncio.sleep')
    async def test_retry_exponential_backoff(self, mock_sleep):
        """Test exponential backoff delay."""
        func = AsyncMock(side_effect=[ValueError("Error"), "success"])
        config = RetryConfig(
            max_attempts=2,
            initial_delay=1.0,
            exponential_base=2.0,
            retryable_exceptions=(ValueError,)
        )
        
        await retry_async(func, config=config)
        
        # Should sleep with delay = 1.0 * 2^0 = 1.0
        mock_sleep.assert_called_once_with(1.0)
    
    @pytest.mark.asyncio
    @patch('asyncio.sleep')
    async def test_retry_respects_max_delay(self, mock_sleep):
        """Test that delay doesn't exceed max_delay."""
        func = AsyncMock(side_effect=[ValueError("Error"), ValueError("Error"), "success"])
        config = RetryConfig(
            max_attempts=3,
            initial_delay=10.0,
            max_delay=15.0,
            exponential_base=2.0,
            retryable_exceptions=(ValueError,)
        )
        
        await retry_async(func, config=config)
        
        # First retry: 10.0 * 2^0 = 10.0
        # Second retry: min(10.0 * 2^1 = 20.0, 15.0) = 15.0
        calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert all(delay <= 15.0 for delay in calls)


@pytest.mark.unit
class TestRetryableDecorator:
    """Test cases for retryable decorator."""
    
    @pytest.mark.asyncio
    async def test_retryable_decorator_success(self):
        """Test retryable decorator on successful function."""
        @retryable(max_attempts=3)
        async def test_func():
            return "success"
        
        result = await test_func()
        
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_retryable_decorator_retries(self):
        """Test retryable decorator retries on failure."""
        call_count = 0
        
        @retryable(max_attempts=3, retryable_exceptions=(ValueError,))
        async def test_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Error")
            return "success"
        
        result = await test_func()
        
        assert result == "success"
        assert call_count == 2

